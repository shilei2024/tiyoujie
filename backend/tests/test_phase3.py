import base64
import io
import json
import os
import secrets
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, transaction
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import ChildAccessGrant, ChildProfile, FamilyMember, GuardianConsent
from apps.accounts.services import create_family, process_pending_deletions, request_deletion
from apps.credentials.services import change_credential, save_credential
from apps.entitlements.models import ResourcePolicy
from apps.metering.models import BudgetPolicy, BudgetWindow, PriceVersion, QuotaWindow, UsageLedger
from apps.metering.services import reconcile
from apps.ocr.models import OCRJob, OCRModel, Outbox
from apps.ocr.providers import Outcome, ProviderFailure, call_provider, parse_result
from apps.ocr.services import cancel_scope, complete, create_job, prepare, recover_jobs, run_job
from apps.problems.images import normalize
from apps.problems.models import Asset, Problem, ProblemAsset, ProblemTextVersion, StoredObject
from apps.problems.services import (
    attach_asset,
    cleanup_objects,
    create_problem,
    delete_problem,
    save_text,
    storage,
    transform_asset,
    upload_asset,
)
from config.errors import AppError
from tests.test_phase2 import ApiCase


def image_upload(size=(100, 80), fmt="PNG", content_type=None, metadata=False):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, "white")
    exif = Image.Exif()
    if metadata:
        exif[270] = "private-unit-metadata"
    image.save(buffer, fmt, exif=exif)
    return SimpleUploadedFile(
        "../../untrusted." + fmt.lower(),
        buffer.getvalue(),
        content_type=content_type
        or {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt],
    )


class ImageCase(ApiCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.private = override_settings(MEDIA_ROOT=self.directory.name)
        self.private.enable()
        self.addCleanup(self.private.disable)
        self.learner = self.child()
        self.problem = create_problem(self.a, {"child_id": self.learner.pk, "chapter": "分数"})

    def upload(self, problem=None):
        return upload_asset(self.a, (problem or self.problem).pk, image_upload())


class ProblemTests(ImageCase):
    def test_image_unlink_keeps_other_references_then_deletes_final_file(self):
        asset = self.upload()
        second = create_problem(self.a, {"child_id": self.learner.pk})
        attach_asset(self.a, second.pk, asset.pk, 1)
        self.problem.refresh_from_db()
        path = storage().path(asset.object.object_key)
        url = f"/api/v1/problems/{self.problem.pk}/assets/{asset.pk}/remove/"
        data = {"expected_revision": self.problem.revision}
        self.assertEqual(self.client_for(self.b).post(url, data, format="json").status_code, 404)
        self.assertEqual(self.client.post(url, data, format="json").status_code, 200)
        cleanup_objects()
        self.assertTrue(path.exists())
        second.refresh_from_db()
        url = f"/api/v1/problems/{second.pk}/assets/{asset.pk}/remove/"
        self.assertEqual(
            self.client.post(
                url, {"expected_revision": second.revision}, format="json"
            ).status_code,
            200,
        )
        cleanup_objects()
        self.assertFalse(path.exists())

    def test_database_preserves_text_history_and_owns_parent(self):
        first = ProblemTextVersion.objects.create(
            problem=self.problem, number=1, origin="manual", text="original", confirmed=True
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProblemTextVersion.objects.filter(pk=first.pk).update(text="overwritten")
        other = create_problem(self.a, {"child_id": self.learner.pk})
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProblemTextVersion.objects.create(
                problem=other, number=1, origin="manual", text="foreign parent", parent=first
            )

    def test_database_rejects_cross_child_links_and_unconfirmed_current_text(self):
        asset = self.upload()
        sibling = self.child("另一个孩子")
        other = create_problem(self.a, {"child_id": sibling.pk})
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProblemAsset.objects.create(problem=other, asset=asset)
        candidate = ProblemTextVersion.objects.create(
            problem=self.problem, number=1, text="candidate", origin="ocr"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Problem.objects.filter(pk=self.problem.pk).update(current_text=candidate)

    def test_orphaned_file_is_removed_only_after_safety_window(self):
        asset = self.upload()
        live_path = storage().path(asset.object.object_key)
        orphan_key = "ab/" + uuid.uuid4().hex + ".jpg"
        storage().put(orphan_key, image_upload().read())
        orphan_path = storage().path(orphan_key)
        cleanup_objects()
        self.assertTrue(orphan_path.exists())
        old = (timezone.now() - timedelta(hours=2)).timestamp()
        os.utime(orphan_path, (old, old))
        cleanup_objects()
        self.assertFalse(orphan_path.exists())
        self.assertTrue(live_path.exists())

    def test_anonymous_foreign_and_student_mutation_permissions(self):
        asset = self.upload()
        paths = [
            f"problems/{self.problem.pk}/",
            f"problems/{self.problem.pk}/text-versions/",
            f"assets/{asset.pk}/content/",
        ]
        for path in paths:
            self.assertEqual(APIClient().get("/api/v1/" + path).status_code, 401)
            self.assertEqual(self.client_for(self.b).get("/api/v1/" + path).status_code, 404)
        member = FamilyMember.objects.create(user=self.student, family=self.family, role="student")
        ChildAccessGrant.objects.create(member=member, child=self.learner)
        client = self.client_for(self.student)
        self.assertEqual(client.get(f"/api/v1/assets/{asset.pk}/content/").status_code, 200)
        self.assertEqual(
            client.post(
                f"/api/v1/problems/{self.problem.pk}/text/",
                {"text": "1+1", "confirmed": True, "expected_revision": 2},
                format="json",
            ).status_code,
            403,
        )

    def test_manual_text_versions_are_immutable_and_require_revision_and_confirmation(self):
        url = f"/api/v1/problems/{self.problem.pk}/text/"
        data = {"text": "求 1/2 + 1/3", "answer": "5/6", "confirmed": False, "expected_revision": 1}
        self.assertEqual(self.client.post(url, data, format="json").status_code, 400)
        data["confirmed"] = True
        first = self.client.post(url, data, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["revision"], 2)
        self.assertEqual(self.client.post(url, data, format="json").status_code, 409)
        self.client.post(
            url, {**data, "text": "修订后的题面", "expected_revision": 2}, format="json"
        )
        self.assertEqual(self.problem.text_versions.count(), 2)
        self.assertEqual(self.problem.text_versions.get(number=1).text, data["text"])
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.current_text.text, "修订后的题面")

    def test_search_filters_pagination_and_old_draft_compatibility(self):
        save_text(
            self.a,
            self.problem.pk,
            {"expected_revision": 1, "confirmed": True, "text": "负号与分数", "answer": ""},
        )
        url = f"/api/v1/problems/?family_id={self.family.pk}&q=分数&chapter=分数"
        self.assertEqual(self.client.get(url).json()["count"], 1)
        self.assertEqual(self.client.get(url + "&page=2").status_code, 400)
        self.assertEqual(self.client.get(url + "&date_from=bad").status_code, 400)
        self.assertEqual(self.client.get(url + "&grade=99").status_code, 400)
        for _ in range(20):
            create_problem(self.a, {"child_id": self.learner.pk})
        result = self.client.get(f"/api/v1/problems/?family_id={self.family.pk}").json()
        self.assertEqual(result["count"], 21)
        self.assertEqual(len(result["results"]), 20)
        self.assertEqual(result["next"], 2)

    def test_metadata_cannot_transfer_children_or_forge_owner(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/problems/",
                {"child_id": str(self.learner.pk), "owner_id": self.b.pk},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/problems/{self.problem.pk}/update/",
                {"child_id": str(self.learner.pk), "expected_revision": 1},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/problems/{self.problem.pk}/update/",
                {"chapter": "代数", "expected_revision": 1},
                format="json",
            ).status_code,
            200,
        )

    def test_upload_normalizes_and_strips_metadata_and_filename(self):
        image = image_upload(fmt="JPEG", metadata=True)
        response = self.client.post(
            f"/api/v1/problems/{self.problem.pk}/assets/", {"file": image}, format="multipart"
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("object_key", response.json())
        asset = Asset.objects.get(pk=response.json()["id"])
        data = storage().read(asset.object.object_key)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertEqual(len(result.getexif()), 0)
        self.assertNotIn(b"private-unit-metadata", data)
        self.assertTrue(storage().path(asset.object.object_key).is_file())

    def test_fake_svg_declared_mime_animation_and_truncation_are_rejected(self):
        for data in (
            b"<svg><script>1</script></svg>",
            b"<html>not image</html>",
            image_upload().read()[:30],
        ):
            with self.assertRaises(AppError):
                normalize(SimpleUploadedFile("payload.png", data, content_type="image/png"))
        with self.assertRaises(AppError):
            normalize(image_upload(content_type="image/jpeg"))
        buffer = io.BytesIO()
        Image.new("RGB", (5, 5), "red").save(
            buffer,
            "WEBP",
            save_all=True,
            append_images=[Image.new("RGB", (5, 5), "blue")],
            duration=100,
        )
        with self.assertRaises(AppError):
            normalize(
                SimpleUploadedFile("animated.webp", buffer.getvalue(), content_type="image/webp")
            )

    def test_upload_byte_pixel_storage_and_body_limits(self):
        with override_settings(IMAGE_MAX_PIXELS=10):
            with self.assertRaises(AppError):
                normalize(image_upload())
        with override_settings(IMAGE_MAX_BYTES=10):
            with self.assertRaises(AppError):
                normalize(image_upload())
        with override_settings(FAMILY_STORAGE_BYTES=1):
            with self.assertRaises(AppError):
                self.upload()
        self.assertEqual(StoredObject.objects.count(), 0)
        response = self.client.post(
            "/api/v1/problems/", "x" * 65537, content_type="application/json"
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            self.client.post(
                f"/api/v1/problems/{self.problem.pk}/assets/",
                {"file": [image_upload(), image_upload()]},
                format="multipart",
            ).status_code,
            400,
        )

    def test_path_traversal_and_public_media_routes_are_rejected(self):
        with self.assertRaises(AppError):
            storage().read("../../.env")
        self.assertEqual(self.client.get("/media/any.jpg").status_code, 404)

    def test_crop_rotation_split_and_invalid_batch_are_atomic(self):
        asset = self.upload()
        data = {
            "problem_id": self.problem.pk,
            "expected_revision": 2,
            "split": True,
            "regions": [{"x": 0, "y": 0, "width": 30, "height": 20, "rotation": 90}],
        }
        results = transform_asset(self.a, asset.pk, data)
        self.assertNotEqual(results[0][0].pk, self.problem.pk)
        self.assertEqual((results[0][1].width, results[0][1].height), (20, 30))
        before = Asset.objects.count()
        data["regions"].append({"x": 99, "y": 0, "width": 30, "height": 20, "rotation": 0})
        with self.assertRaises(AppError):
            transform_asset(self.a, asset.pk, data)
        self.assertEqual(Asset.objects.count(), before)

    def test_wrong_child_association_and_foreign_crop_are_denied(self):
        asset = self.upload()
        sibling = self.child("另一个孩子")
        other = create_problem(self.a, {"child_id": sibling.pk})
        with self.assertRaises(AppError):
            attach_asset(self.a, other.pk, asset.pk, 1)
        data = {
            "problem_id": self.problem.pk,
            "expected_revision": 2,
            "split": False,
            "regions": [{"x": 0, "y": 0, "width": 10, "height": 10, "rotation": 0}],
        }
        with self.assertRaises(Http404):
            transform_asset(self.b, asset.pk, data)

    def test_shared_image_survives_one_problem_deletion_then_is_physically_cleaned(self):
        asset = self.upload()
        other = create_problem(self.a, {"child_id": self.learner.pk})
        attach_asset(self.a, other.pk, asset.pk, 1)
        path = storage().path(asset.object.object_key)
        delete_problem(self.a, self.problem.pk)
        cleanup_objects()
        self.assertTrue(path.exists())
        self.assertEqual(self.client.get(f"/api/v1/assets/{asset.pk}/content/").status_code, 200)
        delete_problem(self.a, other.pk)
        self.assertEqual(self.client.get(f"/api/v1/assets/{asset.pk}/content/").status_code, 404)
        cleanup_objects()
        self.assertFalse(path.exists())

    def test_child_deletion_cascades_private_files_but_not_foreign_data(self):
        asset = self.upload()
        foreign_child = self.child(family=self.other)
        foreign = create_problem(self.b, {"child_id": foreign_child.pk})
        path = storage().path(asset.object.object_key)
        request_deletion(self.a, self.learner)
        self.assertEqual(self.client.get(f"/api/v1/assets/{asset.pk}/content/").status_code, 404)
        process_pending_deletions()
        cleanup_objects()
        self.assertFalse(path.exists())
        self.assertTrue(Problem.objects.filter(pk=foreign.pk).exists())

    def test_staged_write_failure_is_recoverable(self):
        with patch("apps.problems.storage.PrivateLocalStorage.put", side_effect=OSError()):
            with self.assertRaises(OSError):
                self.upload()
        self.assertEqual(StoredObject.objects.get().state, "purge_pending")
        cleanup_objects()
        self.assertEqual(StoredObject.objects.count(), 0)


class OCRTests(ImageCase):
    def test_transport_deadline_rejects_before_opening_a_connection(self):
        snapshot = {
            "provider": "deepseek",
            "model_name": "unit-vision",
            "max_output_tokens": 128,
            "send_before": (timezone.now() - timedelta(seconds=1)).isoformat(),
        }
        with patch("apps.ocr.providers.build_opener") as opener:
            with self.assertRaises(ProviderFailure) as caught:
                call_provider(snapshot, b"synthetic", "synthetic-unit")
        self.assertTrue(caught.exception.definitely_unsent)
        opener.assert_not_called()

    def test_database_rejects_changing_a_queued_jobs_billing_binding(self):
        job = self.job()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OCRJob.objects.filter(pk=job.pk).update(
                billing_mode="byok", credential_id=uuid.uuid4(), credential_version=1
            )
        job.refresh_from_db()
        self.assertEqual(job.billing_mode, "platform_trial")

    def setUp(self):
        super().setUp()
        self.outbound = override_settings(
            OCR_OUTBOUND_ENABLED=True,
            PLATFORM_AI_ENABLED=True,
            PLATFORM_OCR_CONFIGURED_PROVIDERS={"deepseek"},
            PLATFORM_OCR_KEYS={"deepseek": "synthetic-unit-platform"},
            CREDENTIAL_KEYS_JSON=json.dumps(
                {"test": base64.b64encode(secrets.token_bytes(32)).decode()}
            ),
            CREDENTIAL_ACTIVE_KEY_VERSION="test",
        )
        self.outbound.enable()
        self.addCleanup(self.outbound.disable)
        self.asset = self.upload()
        self.problem.refresh_from_db()
        GuardianConsent.objects.create(
            child=self.learner, guardian=self.a, scope="deepseek", notice_version="2026-10-v1"
        )
        self.model = OCRModel.objects.create(
            provider="deepseek",
            model_name="unit-vision",
            enabled=True,
            supports_vision=True,
            runtime_approved=True,
            max_output_tokens=128,
            notice="Synthetic provider notice for isolated tests",
            notice_version="unit-v1",
            official_source="https://api-docs.deepseek.com/guides/vision/",
        )
        self.policy = BudgetPolicy.objects.create(
            platform_enabled=True,
            timezone_name="UTC",
            lifetime_limit=1000000,
            month_limit=1000000,
            day_limit=1000000,
            family_day_limit=1000000,
            family_daily_quota=5,
            family_total_quota=10,
            user_daily_quota=5,
            family_pending_limit=10,
        )
        self.price = PriceVersion.objects.create(
            model=self.model,
            currency="CNY",
            input_per_million=1000000,
            output_per_million=2000000,
            input_token_bound=10000,
            bound_reviewed=True,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2028, 1, 1, tzinfo=UTC),
            evidence="Synthetic upper bound",
        )

    def data(self, **changes):
        return {
            "asset_id": self.asset.pk,
            "model_id": self.model.pk,
            "billing_mode": "platform_trial",
            "expected_revision": self.problem.revision,
            "notice_version": "unit-v1",
            "cost_confirmed": True,
            **changes,
        }

    def job(self, **changes):
        return create_job(self.a, self.problem.pk, self.data(**changes), uuid.uuid4().hex)

    def outcome(self, text="图像中的数学题"):
        return Outcome({"text": text, "confidence": 0.4, "uncertainties": ["请核对负号"]}, (10, 5))

    def test_idempotency_replay_conflict_and_atomic_reservation(self):
        key = uuid.uuid4().hex
        first = create_job(self.a, self.problem.pk, self.data(), key)
        self.assertEqual(first.pk, create_job(self.a, self.problem.pk, self.data(), key).pk)
        with self.assertRaises(AppError):
            create_job(self.a, self.problem.pk, self.data(notice_version="changed"), key)
        self.assertEqual(Outbox.objects.count(), 1)
        self.assertEqual(UsageLedger.objects.count(), 1)
        self.assertEqual(BudgetWindow.objects.count(), 4)
        self.assertTrue(all(window.reserved == 10256 for window in BudgetWindow.objects.all()))

    def test_disabled_missing_price_budget_key_and_mode_fail_closed(self):
        with patch("apps.ocr.services.call_provider") as provider:
            for changes in (
                {"OCR_OUTBOUND_ENABLED": False},
                {"PLATFORM_AI_ENABLED": False},
                {"PLATFORM_OCR_CONFIGURED_PROVIDERS": set()},
            ):
                with override_settings(**changes):
                    with self.assertRaises(AppError):
                        self.job()
            self.price.bound_reviewed = False
            self.price.save()
            with self.assertRaises(AppError):
                self.job()
            provider.assert_not_called()
        self.assertEqual(OCRJob.objects.count(), 0)
        self.assertEqual(BudgetWindow.objects.count(), 0)

    def test_all_budget_limits_reject_without_partial_window_updates(self):
        for name in ("lifetime_limit", "month_limit", "day_limit", "family_day_limit"):
            original = getattr(self.policy, name)
            setattr(self.policy, name, 100)
            self.policy.save()
            with self.assertRaises(AppError):
                self.job()
            self.assertEqual(UsageLedger.objects.count(), 0)
            self.assertEqual(BudgetWindow.objects.count(), 0)
            setattr(self.policy, name, original)
            self.policy.save()

    def test_success_remains_candidate_and_duplicate_delivery_does_not_rebill(self):
        job = self.job()
        with patch("apps.ocr.services.call_provider", return_value=self.outcome()) as provider:
            run_job(job.pk)
            run_job(job.pk)
        provider.assert_called_once()
        job.refresh_from_db()
        self.problem.refresh_from_db()
        self.assertEqual(job.status, "needs_review")
        self.assertIsNone(self.problem.current_text_id)
        self.assertFalse(self.problem.text_versions.get().confirmed)
        ledger = UsageLedger.objects.get(job=job)
        self.assertEqual(ledger.settled_micros, 20)
        self.assertTrue(
            all(row.reserved == 0 and row.settled == 20 for row in BudgetWindow.objects.all())
        )
        self.assertTrue(
            all(row.consumed == 1 and row.reserved == 0 for row in QuotaWindow.objects.all())
        )

    def test_manual_edit_during_ocr_is_not_overwritten(self):
        job = self.job()

        def response(*args):
            save_text(
                self.a,
                self.problem.pk,
                {"expected_revision": 2, "confirmed": True, "text": "人工确认题干", "answer": ""},
            )
            return self.outcome()

        with patch("apps.ocr.services.call_provider", side_effect=response):
            run_job(job.pk)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.current_text.text, "人工确认题干")
        self.assertEqual(self.problem.text_versions.count(), 2)

    def test_timeout_unknown_cost_holds_budget_and_halts_without_retry(self):
        job = self.job()
        with patch(
            "apps.ocr.services.call_provider", side_effect=ProviderFailure("PROVIDER_TIMEOUT")
        ) as provider:
            run_job(job.pk)
            run_job(job.pk)
        provider.assert_called_once()
        self.assertEqual(UsageLedger.objects.get(job=job).status, "unknown")
        self.assertTrue(
            all(
                window.reserved == 10256 and window.settled == 0
                for window in BudgetWindow.objects.all()
            )
        )
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.halted)
        with self.assertRaises(AppError):
            self.job()

    def test_usage_beyond_reviewed_bound_halts_future_calls(self):
        job = self.job()
        outcome = self.outcome()
        outcome.usage = (20000, 500)
        with patch("apps.ocr.services.call_provider", return_value=outcome):
            run_job(job.pk)
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.halted)
        self.assertEqual(UsageLedger.objects.get(job=job).settled_micros, 21000)

    def test_invalid_output_with_known_usage_is_charged_but_not_published(self):
        job = self.job()
        with patch(
            "apps.ocr.services.call_provider",
            return_value=Outcome(None, (10, 5), "OCR_OUTPUT_INVALID"),
        ):
            run_job(job.pk)
        self.assertEqual(self.problem.text_versions.count(), 0)
        self.assertEqual(UsageLedger.objects.get(job=job).settled_micros, 20)
        self.assertTrue(
            all(row.consumed == 0 and row.reserved == 0 for row in QuotaWindow.objects.all())
        )

    def test_byok_uses_own_key_and_never_platform_budget_or_fallback(self):
        credential = save_credential(self.a, self.family.pk, "deepseek", "synthetic-unit-own")
        job = self.job(billing_mode="byok", credential_id=credential.pk)
        with patch("apps.ocr.services.call_provider", return_value=self.outcome()) as provider:
            run_job(job.pk)
        self.assertEqual(provider.call_args.args[-1], "synthetic-unit-own")
        self.assertEqual(BudgetWindow.objects.count(), 0)
        self.assertEqual(QuotaWindow.objects.count(), 0)
        ledger = UsageLedger.objects.get(job=job)
        self.assertEqual(ledger.status, "byok_usage_known")
        self.assertIsNone(ledger.settled_micros)
        self.assertEqual(ledger.estimated_micros, 20)

    def test_deleted_or_replaced_key_blocks_queued_job_without_provider_call(self):
        credential = save_credential(self.a, self.family.pk, "deepseek", "synthetic-unit-own")
        job = self.job(billing_mode="byok", credential_id=credential.pk)
        change_credential(self.a, credential.pk, delete=True)
        with patch("apps.ocr.services.call_provider") as provider:
            run_job(job.pk)
        provider.assert_not_called()
        self.assertEqual(UsageLedger.objects.get(job=job).status, "not_sent")

    def test_cross_family_credential_image_job_and_cancel_are_denied(self):
        credential = save_credential(self.b, self.other.pk, "deepseek", "synthetic-unit-other")
        with self.assertRaises(Http404):
            self.job(billing_mode="byok", credential_id=credential.pk)
        job = self.job()
        client = self.client_for(self.b)
        self.assertEqual(client.get(f"/api/v1/tasks/{job.pk}/").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/tasks/{job.pk}/cancel/").status_code, 404)

    def test_consent_revocation_cancels_before_send_and_releases_once(self):
        job = self.job()
        GuardianConsent.objects.filter(child=self.learner, scope="deepseek").update(
            revoked_at=timezone.now()
        )
        with patch("apps.ocr.services.call_provider") as provider:
            run_job(job.pk)
            run_job(job.pk)
        provider.assert_not_called()
        self.assertTrue(
            all(row.reserved == 0 and row.settled == 0 for row in BudgetWindow.objects.all())
        )

    def test_pending_cancel_and_running_cancel_have_distinct_cost_semantics(self):
        job = self.job()
        with transaction.atomic():
            cancel_scope(pk=job.pk)
            cancel_scope(pk=job.pk)
        self.assertTrue(all(row.reserved == 0 for row in BudgetWindow.objects.all()))
        running = self.job()
        prepared = prepare(running.pk)
        with transaction.atomic():
            cancel_scope(pk=running.pk)
        complete(running.pk, prepared[1], self.outcome())
        running.refresh_from_db()
        self.assertEqual(running.status, "cancelled")
        self.assertEqual(UsageLedger.objects.get(job=running).settled_micros, 20)
        self.assertEqual(self.problem.text_versions.count(), 0)

    def test_crash_after_send_marker_becomes_unknown_and_is_not_redispatched(self):
        job = self.job()
        prepare(job.pk)
        with patch("apps.ocr.services.publish_outbox"):
            recover_jobs(timezone.now() + timedelta(minutes=2))
        job.refresh_from_db()
        self.assertEqual(job.error_code, "PROVIDER_OUTCOME_UNKNOWN")
        self.assertEqual(UsageLedger.objects.get(job=job).status, "unknown")
        with patch("apps.ocr.services.call_provider") as provider:
            run_job(job.pk)
        provider.assert_not_called()

    def test_boundary_expired_reservation_and_budget_lowering_fail_before_send(self):
        with patch(
            "apps.ocr.services.timezone.now",
            return_value=datetime(2026, 10, 22, 23, 59, 30, tzinfo=UTC),
        ):
            with self.assertRaises(AppError):
                self.job()
        job = self.job()
        OCRJob.objects.filter(pk=job.pk).update(
            reservation_until=timezone.now() - timedelta(seconds=1)
        )
        with patch("apps.ocr.services.call_provider") as provider:
            run_job(job.pk)
        provider.assert_not_called()
        other = self.job()
        self.policy.day_limit = 1
        self.policy.save()
        with patch("apps.ocr.services.call_provider") as provider:
            run_job(other.pk)
        provider.assert_not_called()

    def test_reconciliation_requires_operator_reason_and_leaves_circuit_halted(self):
        job = self.job()
        with patch(
            "apps.ocr.services.call_provider", side_effect=ProviderFailure("PROVIDER_TIMEOUT")
        ):
            run_job(job.pk)
        with self.assertRaises(AppError):
            reconcile(self.a, job, 7, "Supplier verified cost")
        operator = get_user_model().objects.create_superuser(
            username="reconciler", password=secrets.token_urlsafe(32)
        )
        reconcile(operator, job, 7, "Supplier verified cost")
        with self.assertRaises(AppError):
            reconcile(operator, job, 7, "Repeat")
        self.assertTrue(
            all(
                window.reserved == 0 and window.settled == 7
                for window in BudgetWindow.objects.all()
            )
        )
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.halted)

    def test_admin_cannot_resume_with_unresolved_cost_or_mutate_price_version(self):
        job = self.job()
        with patch(
            "apps.ocr.services.call_provider", side_effect=ProviderFailure("PROVIDER_TIMEOUT")
        ):
            run_job(job.pk)
        operator = get_user_model().objects.create_superuser(
            username="budget-operator", password=secrets.token_urlsafe(32)
        )
        self.client.force_login(operator)
        self.policy.refresh_from_db()
        data = {field.name: getattr(self.policy, field.name) for field in self.policy._meta.fields}
        data.pop("halted")
        data["reason"] = "Attempt to resume before reconciliation"
        response = self.client.post("/admin/metering/budgetpolicy/base/change/", data)
        self.assertEqual(response.status_code, 200)
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.halted)
        self.assertContains(response, "未决平台费用完成对账前不能解除熔断")
        response = self.client.post(
            f"/admin/metering/priceversion/{self.price.pk}/change/",
            {"input_per_million": 1, "reason": "Attempt to edit historical price"},
        )
        self.assertEqual(response.status_code, 403)

    def test_platform_experience_is_limited_even_when_feature_membership_exists(self):
        self.policy.family_total_quota = 1
        self.policy.save()
        first = self.job()
        with patch("apps.ocr.services.call_provider", return_value=self.outcome()):
            run_job(first.pk)
        with self.assertRaises(AppError):
            self.job()

    def test_parser_rejects_injected_fields_nan_and_truncated_results(self):
        for candidate in (
            {"text": "1+1", "confidence": 1, "uncertainties": [], "tool": "execute"},
            {"text": "1+1", "confidence": float("nan"), "uncertainties": []},
        ):
            result = parse_result(
                {
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": json.dumps(candidate)}}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                }
            )
            self.assertIsNone(result.candidate)
            self.assertEqual(result.usage, (1, 2))
        result = parse_result(
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        )
        self.assertIsNone(result.candidate)
        self.assertIsNone(result.usage)


class MeteringConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.options = override_settings(
            MEDIA_ROOT=self.directory.name,
            OCR_OUTBOUND_ENABLED=True,
            PLATFORM_AI_ENABLED=True,
            PLATFORM_OCR_CONFIGURED_PROVIDERS={"deepseek"},
            PLATFORM_OCR_KEYS={"deepseek": "synthetic-unit-platform"},
        )
        self.options.enable()
        self.addCleanup(self.options.disable)
        ResourcePolicy.objects.create(basic_child_limit=3, max_families=3)
        self.model = OCRModel.objects.create(
            provider="deepseek",
            model_name="unit-concurrent",
            enabled=True,
            runtime_approved=True,
            supports_vision=True,
            max_output_tokens=128,
            notice="Synthetic notice",
            notice_version="unit-v1",
            official_source="https://api-docs.deepseek.com/guides/vision/",
        )
        self.policy = BudgetPolicy.objects.create(
            platform_enabled=True,
            timezone_name="UTC",
            lifetime_limit=1000000,
            month_limit=1000000,
            day_limit=1000000,
            family_day_limit=1000000,
            family_daily_quota=10,
            family_total_quota=10,
            user_daily_quota=10,
            family_pending_limit=10,
        )
        PriceVersion.objects.create(
            model=self.model,
            currency="CNY",
            input_per_million=1000000,
            output_per_million=2000000,
            input_token_bound=10000,
            bound_reviewed=True,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2028, 1, 1, tzinfo=UTC),
            evidence="Synthetic bound",
        )
        self.scopes = []
        for index in range(2):
            user = get_user_model().objects.create_user(username=f"race-{index}")
            family = create_family(user, f"race-{index}")
            child = ChildProfile.objects.create(family=family, nickname="race")
            for scope in ("profile", "deepseek"):
                GuardianConsent.objects.create(
                    child=child, guardian=user, scope=scope, notice_version="2026-10-v1"
                )
            problem = create_problem(user, {"child_id": child.pk})
            asset = upload_asset(user, problem.pk, image_upload())
            self.scopes.append((user.pk, problem.pk, asset.pk))

    def race(self, same_family=False):
        barrier = Barrier(2)

        def execute(scope):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                user = get_user_model().objects.get(pk=scope[0])
                data = {
                    "asset_id": scope[2],
                    "model_id": self.model.pk,
                    "billing_mode": "platform_trial",
                    "expected_revision": 2,
                    "notice_version": "unit-v1",
                    "cost_confirmed": True,
                }
                return str(create_job(user, scope[1], data, uuid.uuid4().hex).pk)
            except AppError as error:
                return error.public_code
            finally:
                close_old_connections()

        with (
            patch("apps.ocr.services.publish_outbox"),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(
                executor.map(execute, [self.scopes[0]] * 2 if same_family else self.scopes)
            )
        self.assertEqual(OCRJob.objects.count(), 1)
        self.assertEqual(UsageLedger.objects.count(), 1)
        return results

    def test_last_global_lifetime_budget_is_atomic(self):
        self.policy.lifetime_limit = 10256
        self.policy.save()
        self.assertEqual(self.race().count("BUDGET_EXHAUSTED"), 1)

    def test_last_global_month_budget_is_atomic(self):
        self.policy.month_limit = 10256
        self.policy.save()
        self.assertEqual(self.race().count("BUDGET_EXHAUSTED"), 1)

    def test_last_global_day_budget_is_atomic(self):
        self.policy.day_limit = 10256
        self.policy.save()
        self.assertEqual(self.race().count("BUDGET_EXHAUSTED"), 1)

    def test_last_family_day_budget_is_atomic(self):
        self.policy.family_day_limit = 10256
        self.policy.save()
        self.assertEqual(self.race(same_family=True).count("BUDGET_EXHAUSTED"), 1)

    def test_last_family_daily_quota_is_atomic(self):
        self.policy.family_daily_quota = 1
        self.policy.save()
        self.assertEqual(self.race(same_family=True).count("QUOTA_EXHAUSTED"), 1)

    def test_last_family_lifetime_quota_is_atomic(self):
        self.policy.family_total_quota = 1
        self.policy.save()
        self.assertEqual(self.race(same_family=True).count("QUOTA_EXHAUSTED"), 1)

    def test_last_user_daily_quota_is_atomic(self):
        self.policy.user_daily_quota = 1
        self.policy.save()
        self.assertEqual(self.race(same_family=True).count("QUOTA_EXHAUSTED"), 1)

    def test_duplicate_worker_claims_only_invoke_provider_once(self):
        self.policy.family_daily_quota = 1
        self.policy.save()
        self.race(same_family=True)
        job = OCRJob.objects.get()
        barrier = Barrier(2)

        def execute(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                run_job(job.pk)
            finally:
                close_old_connections()

        outcome = Outcome({"text": "synthetic", "confidence": None, "uncertainties": []}, (10, 5))
        with (
            patch("apps.ocr.services.call_provider", return_value=outcome) as provider,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            list(executor.map(execute, range(2)))
        provider.assert_called_once()
        self.assertEqual(ProblemTextVersion.objects.filter(ocr_job_id=job.pk).count(), 1)
