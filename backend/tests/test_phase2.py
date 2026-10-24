import base64
import json
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import (
    AuthIdentity,
    AuthSession,
    ChildProfile,
    Family,
    FamilyMember,
    GuardianConsent,
)
from apps.accounts.security import issue_session
from apps.accounts.services import create_family, process_pending_deletions
from apps.credentials.models import UserProviderCredential
from apps.credentials.services import (
    change_credential,
    credential_for_use,
    decrypt,
    rotate_master_key,
    save_credential,
)
from apps.entitlements.models import (
    EntitlementEvent,
    EntitlementGrant,
    FamilyNotification,
    PromotionCampaign,
    ResourcePolicy,
)
from apps.entitlements.services import (
    active_grants,
    add_months,
    child_limit,
    claim,
    eligible,
    manual_grant,
    process_entitlements,
)
from config.errors import AppError


class ApiCase(TestCase):
    def setUp(self):
        self.options = override_settings(
            AUTH_RATE_LIMIT_COUNT=1000, AUTH_THROTTLE_NAMESPACE=uuid.uuid4().hex
        )
        self.options.enable()
        self.addCleanup(self.options.disable)
        ResourcePolicy.objects.create(basic_child_limit=2, max_families=3)
        self.a = get_user_model().objects.create_user(username="guardian-a")
        self.b = get_user_model().objects.create_user(username="guardian-b")
        self.student = get_user_model().objects.create_user(username="student")
        self.family = create_family(self.a, "家庭 A")
        self.other = create_family(self.b, "家庭 B")
        self.client = self.client_for(self.a)

    def client_for(self, user):
        client = APIClient()
        tokens = issue_session(user)
        client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access_token"])
        return client

    def child(self, nickname="昵称", family=None):
        family = family or self.family
        child = ChildProfile.objects.create(family=family, nickname=nickname)
        GuardianConsent.objects.create(
            child=child, guardian=family.owner, scope="profile", notice_version="2026-10-v1"
        )
        return child

    def child_data(self):
        return {
            "family_id": str(self.family.pk),
            "nickname": "新昵称",
            "guardian_confirmed": True,
            "notice_version": "2026-10-v1",
        }

    def campaign(self, **changes):
        now = timezone.now()
        return PromotionCampaign.objects.create(
            name="测试活动",
            status="active",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(days=1),
            allow_existing=True,
            features=["extra_child_profiles"],
            child_profile_limit=4,
            **changes,
        )


class AuthenticationTests(ApiCase):
    def test_anonymous_cannot_read_private_resources(self):
        for path in ("families/", "children/", "provider-credentials/", "entitlements/me/"):
            self.assertEqual(APIClient().get("/api/v1/" + path).status_code, 401)

    def test_plain_tokens_are_not_saved_and_logout_revokes(self):
        tokens = issue_session(self.a)
        session = AuthSession.objects.get(user=self.a, access_expires_at=tokens["expires_at"])
        self.assertNotIn(tokens["access_token"], session.access_hash)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access_token"])
        self.assertEqual(client.post("/api/v1/auth/logout/").status_code, 204)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)

    def test_refresh_rotates_and_reuse_revokes_new_access(self):
        old = issue_session(self.a)
        client = APIClient()
        response = client.post(
            "/api/v1/auth/refresh/", {"refresh_token": old["refresh_token"]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        new = response.json()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + old["access_token"])
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)
        response = client.post(
            "/api/v1/auth/refresh/", {"refresh_token": old["refresh_token"]}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        client.credentials(HTTP_AUTHORIZATION="Bearer " + new["access_token"])
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)

    def test_expired_access_is_rejected(self):
        AuthSession.objects.filter(user=self.a).update(
            access_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_dev_login_off_by_default_and_production_refuses_even_flagged(self):
        client = APIClient()
        self.assertEqual(
            client.post(
                "/api/v1/auth/dev-login/", {"identity": "tester"}, format="json"
            ).status_code,
            404,
        )
        with override_settings(APP_ENV="prod", DEV_LOGIN_ENABLED=True):
            self.assertEqual(
                client.post(
                    "/api/v1/auth/dev-login/", {"identity": "tester"}, format="json"
                ).status_code,
                404,
            )

    def test_explicit_test_adapter_is_labelled_and_non_admin(self):
        with override_settings(DEV_LOGIN_ENABLED=True):
            response = APIClient().post(
                "/api/v1/auth/dev-login/", {"identity": "local-tester"}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["is_test_login"])
        self.assertFalse(get_user_model().objects.get(pk=response.json()["user"]["id"]).is_staff)

    def test_wechat_rejects_client_identity_and_missing_configuration(self):
        client = APIClient()
        self.assertEqual(
            client.post(
                "/api/v1/auth/wechat-login/", {"openid": "forged", "code": "short"}, format="json"
            ).status_code,
            400,
        )
        with override_settings(WECHAT_APP_ID="", WECHAT_APP_SECRET=""):
            self.assertEqual(
                client.post(
                    "/api/v1/auth/wechat-login/", {"code": "short"}, format="json"
                ).status_code,
                503,
            )

    @patch("apps.accounts.views.exchange_code", return_value="unit-openid")
    def test_wechat_identity_is_server_resolved_and_not_returned(self, exchange):
        response = APIClient().post(
            "/api/v1/auth/wechat-login/", {"code": "one-time-code"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("openid", response.content.decode())
        self.assertTrue(
            AuthIdentity.objects.filter(provider="wechat", subject="unit-openid").exists()
        )

    def test_redis_login_rate_limit_and_failure_closed(self):
        client = APIClient()
        with override_settings(DEV_LOGIN_ENABLED=True, AUTH_RATE_LIMIT_COUNT=1):
            self.assertEqual(
                client.post(
                    "/api/v1/auth/dev-login/", {"identity": "limited"}, format="json"
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/auth/dev-login/", {"identity": "limited"}, format="json"
                ).status_code,
                429,
            )
        with (
            override_settings(DEV_LOGIN_ENABLED=True),
            patch("apps.accounts.security.Redis.from_url", side_effect=OSError()),
        ):
            self.assertEqual(
                client.post(
                    "/api/v1/auth/dev-login/", {"identity": "limited"}, format="json"
                ).status_code,
                503,
            )


class FamilyTests(ApiCase):
    def test_staff_api_session_has_no_family_or_private_object_bypass(self):
        self.b.is_staff = True
        self.b.is_superuser = True
        self.b.save()
        client = self.client_for(self.b)
        child = self.child()
        for path in (
            f"families/{self.family.pk}/",
            f"children/{child.pk}/",
            f"children/{child.pk}/consents/",
            f"provider-credentials/?family_id={self.family.pk}",
            f"entitlements/me/?family_id={self.family.pk}",
        ):
            self.assertEqual(client.get("/api/v1/" + path).status_code, 404)

    def test_consent_renewal_has_one_active_scope_and_portable_update_checks_access(self):
        child = self.child()
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    f"/api/v1/children/{child.pk}/consents/",
                    {"scope": "profile", "notice_version": "2026-10-v1"},
                    format="json",
                ).status_code,
                201,
            )
        self.assertEqual(
            GuardianConsent.objects.filter(
                child=child, scope="profile", revoked_at__isnull=True
            ).count(),
            1,
        )
        path = f"/api/v1/children/{child.pk}/update/"
        self.assertEqual(
            self.client.post(path, {"nickname": "更新"}, format="json").status_code, 200
        )
        self.assertEqual(
            self.client_for(self.b).post(path, {"nickname": "非法"}, format="json").status_code, 404
        )

    def test_foreign_family_read_write_and_children_list_are_rejected(self):
        for method, path, data in (
            ("get", f"families/{self.other.pk}/", None),
            ("patch", f"families/{self.other.pk}/", {"name": "非法"}),
            ("get", f"children/?family_id={self.other.pk}", None),
        ):
            response = getattr(self.client, method)("/api/v1/" + path, data, format="json")
            self.assertEqual(response.status_code, 404)

    def test_family_owner_cannot_be_forged(self):
        response = self.client.post(
            "/api/v1/families/", {"name": "新家庭", "owner_id": self.b.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_child_create_requires_consent_and_valid_current_notice(self):
        for change in ({"guardian_confirmed": False}, {"notice_version": "old"}):
            response = self.client.post(
                "/api/v1/children/", {**self.child_data(), **change}, format="json"
            )
            self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/v1/children/", self.child_data(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            GuardianConsent.objects.filter(child_id=response.json()["id"], scope="profile").exists()
        )

    def test_child_foreign_crud_is_rejected(self):
        child = self.child(family=self.other)
        for method, data in (
            ("get", None),
            ("patch", {"nickname": "越权"}),
            ("delete", {"confirm": True}),
        ):
            self.assertEqual(
                getattr(self.client, method)(
                    f"/api/v1/children/{child.pk}/", data, format="json"
                ).status_code,
                404,
            )

    def test_student_only_sees_granted_child_and_cannot_modify(self):
        one, two = self.child("甲"), self.child("乙")
        invitation = self.client.post(
            f"/api/v1/families/{self.family.pk}/invitations/",
            {"role": "student", "child_ids": [str(one.pk)]},
            format="json",
        )
        client = self.client_for(self.student)
        self.assertEqual(
            client.post(
                "/api/v1/invitations/accept/", invitation.json(), format="json"
            ).status_code,
            400,
        )
        token = {"invitation_token": invitation.json()["invitation_token"]}
        self.assertEqual(
            client.post("/api/v1/invitations/accept/", token, format="json").status_code, 200
        )
        self.assertEqual(
            client.post("/api/v1/invitations/accept/", token, format="json").status_code, 400
        )
        self.assertEqual(client.get(f"/api/v1/children/{two.pk}/").status_code, 404)
        self.assertEqual(
            client.patch(
                f"/api/v1/children/{one.pk}/", {"nickname": "改名"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            client.get(f"/api/v1/children/?family_id={self.family.pk}").json()["count"], 1
        )
        self.assertEqual(
            client.get(f"/api/v1/provider-credentials/?family_id={self.family.pk}").status_code, 403
        )
        member = FamilyMember.objects.get(user=self.student, family=self.family)
        self.assertEqual(
            self.client.delete(f"/api/v1/family-members/{member.pk}/").status_code, 204
        )
        self.assertEqual(client.get(f"/api/v1/children/{one.pk}/").status_code, 401)

    def test_cross_family_invitation_and_family_transfer_are_rejected(self):
        child = self.child(family=self.other)
        response = self.client.post(
            f"/api/v1/families/{self.family.pk}/invitations/",
            {"role": "guardian", "child_ids": [str(child.pk)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        own = self.child()
        self.assertEqual(
            self.client.patch(
                f"/api/v1/children/{own.pk}/", {"family_id": str(self.other.pk)}, format="json"
            ).status_code,
            400,
        )

    def test_consent_revocation_blocks_edit_but_preserves_read_and_delete(self):
        child = self.child()
        consent = GuardianConsent.objects.get(child=child)
        self.assertEqual(
            self.client.delete(f"/api/v1/children/{child.pk}/consents/{consent.pk}/").status_code,
            204,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/children/{child.pk}/", {"nickname": "改名"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get(f"/api/v1/children/{child.pk}/").status_code, 200)

    def test_child_delete_receipt_purge_and_foreign_data_preservation(self):
        child, other = self.child(), self.child(family=self.other)
        response = self.client.delete(
            f"/api/v1/children/{child.pk}/", {"confirm": True}, format="json"
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get(f"/api/v1/children/{child.pk}/").status_code, 404)
        result = response.json()
        url = f"/api/v1/deletion-requests/{result['task_id']}/"
        self.assertEqual(APIClient().get(url).status_code, 404)
        process_pending_deletions()
        self.assertFalse(ChildProfile.objects.filter(pk=child.pk).exists())
        self.assertTrue(ChildProfile.objects.filter(pk=other.pk).exists())
        self.assertEqual(
            APIClient()
            .get(url, HTTP_X_DELETION_RECEIPT=result["deletion_receipt"])
            .json()["status"],
            "succeeded",
        )

    def test_account_deletion_revokes_access_and_removes_owned_data(self):
        self.child()
        response = self.client.post(
            "/api/v1/account-deletion-jobs/", {"confirm": True}, format="json"
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
        process_pending_deletions()
        self.assertFalse(Family.objects.filter(pk=self.family.pk).exists())
        self.assertTrue(Family.objects.filter(pk=self.other.pk).exists())

    def test_account_deletion_requires_other_members_to_be_handled(self):
        FamilyMember.objects.create(family=self.family, user=self.student, role="student")
        response = self.client.post(
            "/api/v1/account-deletion-jobs/", {"confirm": True}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.a.refresh_from_db()
        self.assertTrue(self.a.is_active)


class CredentialTests(ApiCase):
    def test_portable_state_update_checks_owner_and_versions(self):
        credential = self.create()
        path = f"/api/v1/provider-credentials/{credential.pk}/state/"
        self.assertEqual(
            self.client_for(self.b).post(path, {"enabled": False}, format="json").status_code, 404
        )
        self.assertEqual(self.client.post(path, {"enabled": False}, format="json").status_code, 200)
        credential.refresh_from_db()
        self.assertFalse(credential.enabled)
        self.assertEqual(credential.credential_version, 2)

    def setUp(self):
        super().setUp()
        keys = {name: base64.b64encode(secrets.token_bytes(32)).decode() for name in ("v1", "v2")}
        self.crypto = override_settings(
            CREDENTIAL_KEYS_JSON=json.dumps(keys), CREDENTIAL_ACTIVE_KEY_VERSION="v1"
        )
        self.crypto.enable()
        self.addCleanup(self.crypto.disable)
        self.plaintext = "unit-provider-" + uuid.uuid4().hex

    def create(self):
        return save_credential(self.a, self.family.pk, "deepseek", self.plaintext)

    def test_https_required_and_metadata_never_contains_plaintext_or_ciphertext(self):
        data = {"family_id": str(self.family.pk), "provider": "deepseek", "key": self.plaintext}
        self.assertEqual(
            self.client.post("/api/v1/provider-credentials/", data, format="json").status_code, 400
        )
        response = self.client.post(
            "/api/v1/provider-credentials/", data, format="json", secure=True
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(self.plaintext, response.content.decode())
        self.assertNotIn("ciphertext", response.content.decode())
        credential = UserProviderCredential.objects.get(pk=response.json()["id"])
        self.assertNotIn(self.plaintext.encode(), bytes(credential.ciphertext))
        self.assertEqual(decrypt(credential), self.plaintext)
        self.assertEqual(response.json()["validation_status"], "not_verified")

    def test_no_master_key_is_fail_closed(self):
        with override_settings(CREDENTIAL_KEYS_JSON=""):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(UserProviderCredential.objects.count(), 0)

    def test_cross_family_read_replace_use_delete_are_denied(self):
        credential = self.create()
        client = self.client_for(self.b)
        url = f"/api/v1/provider-credentials/{credential.pk}/"
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.delete(url).status_code, 404)
        self.assertEqual(
            client.post(
                url + "replace/", {"key": self.plaintext}, format="json", secure=True
            ).status_code,
            404,
        )
        with self.assertRaises(Http404):
            credential_for_use(self.b, credential.pk, 1)

    def test_replacement_disabling_deletion_and_version_binding(self):
        credential = self.create()
        replacement = "replacement-unit-" + uuid.uuid4().hex
        url = f"/api/v1/provider-credentials/{credential.pk}/"
        self.assertEqual(
            self.client.post(
                url + "replace/", {"key": replacement}, format="json", secure=True
            ).status_code,
            200,
        )
        with self.assertRaises(AppError):
            credential_for_use(self.a, credential.pk, 1)
        self.assertEqual(credential_for_use(self.a, credential.pk, 2), replacement)
        change_credential(self.a, credential.pk, enabled=False)
        with self.assertRaises(AppError):
            credential_for_use(self.a, credential.pk, 3)
        self.assertEqual(self.client.delete(url).status_code, 204)
        credential.refresh_from_db()
        self.assertEqual(bytes(credential.ciphertext), b"")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_aad_prevents_moving_ciphertext_and_master_rotation_preserves_key(self):
        credential = self.create()
        self.assertEqual(rotate_master_key("v2"), 1)
        credential.refresh_from_db()
        self.assertEqual(credential.key_version, "v2")
        self.assertEqual(decrypt(credential), self.plaintext)
        credential.family_id = self.other.pk
        with self.assertRaises(AppError):
            decrypt(credential)

    def test_admin_has_no_credential_plaintext_model(self):
        self.assertNotIn(UserProviderCredential, admin.site._registry)


class PromotionTests(ApiCase):
    def test_manual_issue_requires_operator_and_reason_and_is_audited(self):
        campaign = self.campaign()
        with self.assertRaises(AppError):
            manual_grant(self.a, self.family.pk, campaign.pk, "Support request")
        operator = get_user_model().objects.create_superuser(
            username="operator", password=secrets.token_urlsafe(32)
        )
        with self.assertRaises(AppError):
            manual_grant(operator, self.family.pk, campaign.pk, " ")
        grant = manual_grant(operator, self.family.pk, campaign.pk, "Support request")
        self.assertEqual(grant.family_id, self.family.pk)
        from apps.accounts.models import AuditEvent

        self.assertTrue(
            AuditEvent.objects.filter(
                actor_id=operator.pk, action="entitlement_manually_issued", reason="Support request"
            ).exists()
        )

    def test_calendar_month_end_leap_year_and_dst(self):
        for start, months, expected in (
            ("2026-08-31", 6, "2027-02-28"),
            ("2027-08-31", 6, "2028-02-29"),
            ("2028-02-29", 6, "2028-08-29"),
            ("2026-01-31", 1, "2026-02-28"),
        ):
            value = datetime.fromisoformat(start + "T02:00:00+00:00")
            self.assertEqual(
                add_months(value, months, "Asia/Shanghai").date().isoformat(), expected
            )
        with self.assertRaises(AppError):
            add_months(datetime(2026, 1, 29, 1, 30, tzinfo=UTC), 2, "Europe/Berlin")

    def test_window_boundaries_existing_users_and_paused_campaign(self):
        campaign = self.campaign()
        self.assertTrue(eligible(self.a, self.family, campaign, campaign.window_start))
        self.assertFalse(eligible(self.a, self.family, campaign, campaign.window_end))
        campaign.allow_existing = False
        campaign.window_start = timezone.now()
        self.assertFalse(eligible(self.a, self.family, campaign, timezone.now()))
        campaign.status = "paused"
        self.assertFalse(eligible(self.a, self.family, campaign, campaign.window_start))

    def test_repeated_claim_does_not_extend_and_pause_does_not_revoke(self):
        campaign = self.campaign()
        grant = claim(self.a, self.family.pk, campaign.pk)
        self.assertEqual(claim(self.a, self.family.pk, campaign.pk).pk, grant.pk)
        self.assertEqual(EntitlementGrant.objects.count(), 1)
        campaign.status = "paused"
        campaign.save()
        self.assertEqual(active_grants(self.family).count(), 1)
        self.assertEqual(EntitlementEvent.objects.filter(kind="granted").count(), 1)

    def test_capacity_and_cross_family_claim(self):
        campaign = self.campaign(capacity=1)
        response = self.client.post(
            f"/api/v1/promotion-campaigns/{campaign.pk}/claim/",
            {"family_id": str(self.other.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        claim(self.a, self.family.pk, campaign.pk)
        with self.assertRaises(AppError):
            claim(self.b, self.other.pk, campaign.pk)

    def test_expiry_restricts_new_profiles_but_preserves_existing_data(self):
        campaign = self.campaign()
        grant = claim(self.a, self.family.pk, campaign.pk)
        for i in range(3):
            self.child(str(i))
        self.assertEqual(child_limit(self.family), 4)
        grant.expires_at = timezone.now() - timedelta(seconds=1)
        grant.starts_at = grant.expires_at - timedelta(days=1)
        grant.save()
        self.assertEqual(child_limit(self.family), 2)
        self.assertEqual(
            self.client.post("/api/v1/children/", self.child_data(), format="json").status_code, 403
        )
        self.assertEqual(
            self.client.get(f"/api/v1/children/?family_id={self.family.pk}").json()["count"], 3
        )
        self.assertFalse(
            self.client.get(f"/api/v1/entitlements/me/?family_id={self.family.pk}").json()[
                "automatic_billing"
            ]
        )

    def test_reminder_failure_retries_idempotently_without_changing_expiry(self):
        campaign = self.campaign(reminder_days=[3])
        grant = claim(self.a, self.family.pk, campaign.pk)
        now = grant.expires_at - timedelta(days=3) + timedelta(minutes=1)
        with patch(
            "apps.entitlements.services.FamilyNotification.objects.get_or_create",
            side_effect=OSError(),
        ):
            with self.assertRaises(OSError):
                process_entitlements(now)
        self.assertEqual(EntitlementEvent.objects.filter(kind="reminder").count(), 0)
        process_entitlements(now)
        process_entitlements(now)
        self.assertEqual(FamilyNotification.objects.count(), 1)
        grant.refresh_from_db()
        self.assertEqual(grant.expires_at, add_months(grant.starts_at, 6, campaign.timezone_name))

    def test_expiry_reconciliation_is_idempotent_and_not_required_for_downgrade(self):
        grant = claim(self.a, self.family.pk, self.campaign().pk)
        later = grant.expires_at + timedelta(seconds=1)
        self.assertEqual(child_limit(self.family, later), 2)
        process_entitlements(later)
        process_entitlements(later)
        self.assertEqual(EntitlementEvent.objects.filter(kind="expired").count(), 1)

    def test_entitlements_and_notifications_are_family_scoped(self):
        for path in ("entitlements/me/", "promotion-campaigns/eligible/", "notifications/"):
            self.assertEqual(
                self.client.get(f"/api/v1/{path}?family_id={self.other.pk}").status_code, 404
            )


class ClaimConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ResourcePolicy.objects.create(basic_child_limit=2, max_families=3)
        self.a = get_user_model().objects.create_user(username="concurrent-a")
        self.b = get_user_model().objects.create_user(username="concurrent-b")
        self.family = create_family(self.a, "A")
        self.other = create_family(self.b, "B")
        now = timezone.now()
        self.campaign = PromotionCampaign.objects.create(
            name="并发测试",
            status="active",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(days=1),
            allow_existing=True,
            features=["bulk_management"],
            capacity=1,
        )

    def run_claims(self, families):
        barrier = Barrier(2)

        def run(pair):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                user = get_user_model().objects.get(pk=pair[0])
                return str(claim(user, pair[1], self.campaign.pk).pk)
            except AppError as error:
                return error.public_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, families))

    def test_same_family_claim_is_atomic(self):
        results = self.run_claims([(self.a.pk, self.family.pk)] * 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(EntitlementGrant.objects.count(), 1)

    def test_campaign_capacity_is_atomic_across_families(self):
        results = self.run_claims([(self.a.pk, self.family.pk), (self.b.pk, self.other.pk)])
        self.assertEqual(results.count("CAMPAIGN_FULL"), 1)
        self.assertEqual(EntitlementGrant.objects.count(), 1)
