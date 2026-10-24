import copy
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import ChildAccessGrant, FamilyMember, GuardianConsent
from apps.accounts.services import process_pending_deletions, request_deletion
from apps.problems.models import Problem
from apps.problems.services import save_text
from apps.question_bank.math_verifier import verify
from apps.question_bank.models import KnowledgePoint, QuestionBankItem, QuestionSource, VariantDraft
from apps.question_bank.services import (
    check_item,
    commit_import,
    create_variant,
    preview_import,
    review_item,
    review_source,
    trusted_items,
)
from config.errors import AppError
from tests.test_phase3 import ImageCase


class MathVerifierTests(SimpleTestCase):
    def test_arithmetic_positive_negative_decimal_fraction(self):
        for expression, answer in [
            ("1/2+1/3", "5/6"),
            ("-2*(3-5)", "4"),
            ("0.1+0.2", "0.3"),
            ("0/3", "0"),
        ]:
            self.assertEqual(
                verify({"kind": "arithmetic", "expression": expression}, answer).result, "correct"
            )
        self.assertEqual(
            verify({"kind": "arithmetic", "expression": "1/2+1/3"}, "2/5").result, "incorrect"
        )

    def test_arithmetic_boundaries_and_unsupported(self):
        for expression in ["1/0", "2+", "9" * 100, "(" * 40 + "1" + ")" * 40, "+" * 70 + "1"]:
            self.assertEqual(
                verify({"kind": "arithmetic", "expression": expression}, "1").result, "invalid"
            )
        for expression in [
            "sqrt(4)",
            "2**3",
            "__import__('os')",
            "1;print(1)",
            "1e99999",
            "x+1",
            "True",
        ]:
            self.assertEqual(
                verify({"kind": "arithmetic", "expression": expression}, "1").result,
                "not_supported",
            )

    def test_linear_positive_negative_and_zero_solutions(self):
        for left, right, answer in [
            ("2*x+1", "5", "2"),
            ("x/2", "-1", "-2"),
            ("x+1", "x+2", "no_solution"),
            ("2*(x+1)", "2*x+2", "all_real"),
        ]:
            self.assertEqual(
                verify({"kind": "linear_equation", "left": left, "right": right}, answer).result,
                "correct",
            )
        self.assertEqual(
            verify({"kind": "linear_equation", "left": "x", "right": "1"}, "0").result, "incorrect"
        )
        self.assertEqual(
            verify({"kind": "linear_equation", "left": "x", "right": "x"}, "0").result, "incorrect"
        )

    def test_linear_boundaries_and_non_linear(self):
        for left in ["x*x", "1/x", "x**2", "sin(x)"]:
            self.assertEqual(
                verify({"kind": "linear_equation", "left": left, "right": "1"}, "1").result,
                "not_supported",
            )
        self.assertEqual(
            verify({"kind": "linear_equation", "left": "x/0", "right": "1"}, "1").result, "invalid"
        )

    def test_choices_positive_negative_duplicate_and_missing(self):
        spec = {"kind": "choice_arithmetic", "expression": "1/2", "options": ["0", "0.5", "1"]}
        self.assertEqual(verify(spec, "B").result, "correct")
        self.assertEqual(verify(spec, "A").result, "incorrect")
        for options in [["1/2", "0.5"], ["1", "2"]]:
            self.assertEqual(verify({**spec, "options": options}, "A").code, "choice_not_unique")
        self.assertEqual(verify({**spec, "options": ["1"]}, "A").result, "invalid")
        self.assertEqual(verify({**spec, "options": ["sqrt(1)", "2"]}, "A").result, "not_supported")

    def test_unknown_geometry_and_bad_schema_fail_closed(self):
        self.assertEqual(verify({"kind": "geometry_proof"}, "proof").result, "not_supported")
        self.assertEqual(
            verify({"kind": "arithmetic", "expression": "1", "verified": True}, "1").result,
            "invalid",
        )
        self.assertEqual(verify([], "1").result, "invalid")


class BankTests(ImageCase):
    def setUp(self):
        super().setUp()
        self.reviewer = get_user_model().objects.create_superuser(username="bank-reviewer")
        KnowledgePoint.objects.create(code="rational", name="有理数")
        self.source = QuestionSource.objects.create(
            name="Isolated unit fixture",
            source_type="original",
            source_reference="Synthetic test only",
            license_name="Unit fixture",
            rights_evidence="Synthetic evidence; not a real license",
            attribution="Unit tests",
            usage_conditions="Isolated test database only",
            allow_public=True,
            valid_from=timezone.now() - timezone.timedelta(days=1),
            valid_until=timezone.now() + timezone.timedelta(days=1),
        )
        self.raw = {
            "source_id": str(self.source.pk),
            "items": [
                {
                    "text": "计算 1/2 + 1/3",
                    "answer": "5/6",
                    "explanation": "通分后相加。",
                    "answer_source": "Unit fixture",
                    "explanation_source": "Unit fixture",
                    "grade": 7,
                    "question_type": "计算",
                    "solution_structure": "通分",
                    "difficulty": 1,
                    "knowledge_points": ["rational"],
                    "math_spec": {"kind": "arithmetic", "expression": "1/2+1/3"},
                }
            ],
        }
        save_text(
            self.a,
            self.problem.pk,
            {
                "text": "求两个分数的和",
                "answer": "",
                "confirmed": True,
                "expected_revision": self.problem.revision,
            },
        )
        self.problem.refresh_from_db()
        self.problem.knowledge_points = ["有理数"]
        self.problem.save()

    def imported(self):
        preview = preview_import(self.reviewer, self.raw)
        commit_import(self.reviewer, self.raw, preview["preview_token"])
        return QuestionBankItem.objects.get()

    def approved(self):
        review_source(self.reviewer, self.source.pk, "approved", "Synthetic evidence checked")
        item = self.imported()
        check_item(self.reviewer, item.pk)
        return review_item(
            self.reviewer,
            item.pk,
            "approved",
            "Synthetic statement and explanation checked",
            statement_checked=True,
            explanation_checked=True,
        )

    def variant(self, item):
        return {
            "bank_item_id": item.pk,
            "text_version_id": self.problem.current_text_id,
            "expected_revision": self.problem.revision,
            "intent": "numbers",
        }

    def test_preview_is_read_only_and_commit_deduplicates_replay(self):
        preview = preview_import(self.reviewer, self.raw)
        self.assertEqual(QuestionBankItem.objects.count(), 0)
        self.assertEqual(
            commit_import(self.reviewer, self.raw, preview["preview_token"])["created"], 1
        )
        self.assertEqual(
            commit_import(self.reviewer, self.raw, preview["preview_token"])["created"], 0
        )
        self.assertEqual(preview_import(self.reviewer, self.raw)["rows"][0]["duplicate"], True)
        self.assertEqual(trusted_items().count(), 0)

    def test_preview_token_binds_actor_content_source_revision_and_expiry(self):
        preview = preview_import(self.reviewer, self.raw)
        other_reviewer = get_user_model().objects.create_superuser(username="other-reviewer")
        with self.assertRaises(AppError):
            commit_import(other_reviewer, self.raw, preview["preview_token"])
        later = time.time() + 601
        with (
            patch("django.core.signing.time.time", return_value=later),
            self.assertRaises(AppError),
        ):
            commit_import(self.reviewer, self.raw, preview["preview_token"])
        changed = copy.deepcopy(self.raw)
        changed["items"][0]["answer"] = "1"
        with self.assertRaises(AppError):
            commit_import(self.reviewer, changed, preview["preview_token"])
        with self.assertRaises(AppError):
            commit_import(self.reviewer, self.raw, "invalid")
        self.source.attribution = "Changed unit fixture"
        self.source.save()
        with self.assertRaises(AppError):
            commit_import(self.reviewer, self.raw, preview["preview_token"])
        self.assertEqual(QuestionBankItem.objects.count(), 0)

    def test_duplicates_inside_batch_and_conflicting_answer(self):
        self.raw["items"].append(copy.deepcopy(self.raw["items"][0]))
        self.assertTrue(preview_import(self.reviewer, self.raw)["rows"][1]["duplicate"])
        self.imported()
        self.raw["items"][0]["answer"] = "1"
        self.assertTrue(preview_import(self.reviewer, self.raw)["rows"][0]["answer_conflict"])

    def test_import_rejects_unknown_point_status_injection_and_bad_formula(self):
        for field, value in [
            ("knowledge_points", ["unknown"]),
            ("review_status", "approved"),
            ("text", "$broken"),
            ("text", "<script>alert(1)</script>"),
        ]:
            raw = copy.deepcopy(self.raw)
            raw["items"][0][field] = value
            with self.assertRaises(ValidationError):
                preview_import(self.reviewer, raw)
        self.assertEqual(QuestionBankItem.objects.count(), 0)

    def test_only_staff_with_explicit_permission_can_import_or_review(self):
        for action in [
            lambda: preview_import(self.a, self.raw),
            lambda: review_source(self.a, self.source.pk, "approved", "unit"),
        ]:
            with self.assertRaises(AppError):
                action()
        self.a.is_staff = True
        self.a.save()
        with self.assertRaises(AppError):
            preview_import(self.a, self.raw)

    def test_missing_license_unknown_and_expired_sources_cannot_be_approved(self):
        for field, value in [
            ("rights_evidence", ""),
            ("allow_public", False),
            ("source_type", "unknown"),
            ("source_type", "user_upload"),
            ("valid_until", timezone.now()),
        ]:
            original = getattr(self.source, field)
            setattr(self.source, field, value)
            self.source.save()
            with self.assertRaises(AppError):
                review_source(self.reviewer, self.source.pk, "approved", "Unit check")
            setattr(self.source, field, original)
            self.source.save()

    def test_machine_check_does_not_publish_and_human_statement_review_required(self):
        review_source(self.reviewer, self.source.pk, "approved", "Unit check")
        item = self.imported()
        self.assertEqual(check_item(self.reviewer, item.pk)["result"], "correct")
        self.assertEqual(trusted_items().count(), 0)
        with self.assertRaises(AppError):
            review_item(self.reviewer, item.pk, "approved", "Unit check")
        review_item(
            self.reviewer,
            item.pk,
            "approved",
            "Unit check",
            statement_checked=True,
            explanation_checked=True,
        )
        self.assertEqual(trusted_items().count(), 1)

    def test_incorrect_answer_cannot_be_overridden_and_unsupported_needs_manual(self):
        review_source(self.reviewer, self.source.pk, "approved", "Unit check")
        self.raw["items"][0]["answer"] = "2/5"
        item = self.imported()
        check_item(self.reviewer, item.pk)
        with self.assertRaises(AppError):
            review_item(
                self.reviewer,
                item.pk,
                "approved",
                "Unit check",
                statement_checked=True,
                explanation_checked=True,
                answer_checked=True,
            )
        item.math_spec = {"kind": "geometry_proof"}
        item.save()
        check_item(self.reviewer, item.pk)
        with self.assertRaises(AppError):
            review_item(
                self.reviewer,
                item.pk,
                "approved",
                "Unit check",
                statement_checked=True,
                explanation_checked=True,
            )
        item = review_item(
            self.reviewer,
            item.pk,
            "approved",
            "Unit check",
            statement_checked=True,
            explanation_checked=True,
            answer_checked=True,
        )
        self.assertEqual(item.verification_status, "human_verified")

    def test_editing_question_invalidates_publication_and_old_math_record(self):
        item = self.approved()
        item.answer = "2/5"
        item.save()
        self.assertEqual(item.revision, 2)
        self.assertEqual(trusted_items().count(), 0)
        with self.assertRaises(AppError):
            review_item(
                self.reviewer,
                item.pk,
                "approved",
                "Unit check",
                statement_checked=True,
                explanation_checked=True,
            )

    def test_source_revision_expiry_and_rejection_remove_results_and_draft_content(self):
        item = self.approved()
        draft = create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        self.source.refresh_from_db()
        self.source.usage_conditions = "Changed fixture rights"
        self.source.save()
        self.assertEqual(trusted_items().count(), 0)
        review_source(self.reviewer, self.source.pk, "approved", "Unit recheck")
        self.assertEqual(trusted_items().count(), 0)
        self.assertEqual(self.client.get(f"/api/v1/question-bank/{item.pk}/").status_code, 404)
        output = self.client.get(f"/api/v1/problems/{self.problem.pk}/variants/").json()["results"][
            0
        ]
        self.assertEqual(output["id"], str(draft.pk))
        self.assertIsNone(output["payload"])

    def test_search_scope_filters_match_reasons_and_private_evidence_omitted(self):
        item = self.approved()
        url = f"/api/v1/problems/{self.problem.pk}/similar/"
        self.assertEqual(self.client_for(self.b).get(url).status_code, 404)
        data = self.client.get(
            url + "?grade=7&difficulty=1&question_type=计算&solution_structure=通分"
        ).json()
        self.assertEqual(data["results"][0]["id"], str(item.pk))
        self.assertGreaterEqual(len(data["results"][0]["match_reasons"]), 5)
        self.assertNotIn("rights_evidence", str(data))
        self.assertEqual(self.client.get(url + "?grade=8").json()["results"], [])

    def test_expired_source_not_returned_even_without_cleanup_job(self):
        self.approved()
        with patch(
            "apps.question_bank.services.timezone.now", return_value=self.source.valid_until
        ):
            self.assertEqual(trusted_items().count(), 0)

    def test_four_variant_intents_stay_private_unverified_and_idempotent(self):
        item = self.approved()
        for intent in ["numbers", "conditions", "reverse", "context"]:
            data = self.variant(item) | {"intent": intent}
            key = uuid.uuid4().hex
            draft = create_variant(self.a, self.problem.pk, data, key)
            self.assertEqual(draft.pk, create_variant(self.a, self.problem.pk, data, key).pk)
            self.assertEqual(draft.verification_status, "generated_unverified")
            self.assertEqual(draft.payload["machine_check"]["result"], "correct")
            with self.assertRaises(AppError):
                create_variant(self.a, self.problem.pk, data | {"intent": "other"}, key)
        self.assertEqual(QuestionBankItem.objects.count(), 1)

    def test_variant_api_rejects_foreign_problem_and_injected_status(self):
        item = self.approved()
        url = f"/api/v1/problems/{self.problem.pk}/variants/"
        headers = {"HTTP_IDEMPOTENCY_KEY": uuid.uuid4().hex}
        self.assertEqual(
            self.client_for(self.b)
            .post(url, self.variant(item), format="json", **headers)
            .status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                url,
                self.variant(item) | {"verification_status": "human_verified"},
                format="json",
                **headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(url, self.variant(item), format="json", **headers).status_code, 201
        )
        self.assertEqual(self.client_for(self.b).get(url).status_code, 404)

    def test_variant_revision_consent_and_draft_limit(self):
        item = self.approved()
        with self.assertRaises(AppError):
            create_variant(
                self.a,
                self.problem.pk,
                self.variant(item) | {"expected_revision": 999},
                uuid.uuid4().hex,
            )
        GuardianConsent.objects.filter(child=self.learner).update(revoked_at=timezone.now())
        with self.assertRaises(AppError):
            create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)

    def test_student_reads_permitted_drafts_but_cannot_generate(self):
        item = self.approved()
        create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        member = FamilyMember.objects.create(user=self.student, family=self.family, role="student")
        ChildAccessGrant.objects.create(member=member, child=self.learner)
        client = self.client_for(self.student)
        url = f"/api/v1/problems/{self.problem.pk}/variants/"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(
            client.post(
                url, self.variant(item), format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex
            ).status_code,
            403,
        )

    def test_variant_limit_and_initial_cross_problem_binding(self):
        item = self.approved()
        first = create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        for _ in range(49):
            VariantDraft.objects.create(
                problem=first.problem,
                text_version=first.text_version,
                payload=first.payload,
                generator=first.generator,
                intent=first.intent,
                created_by=self.a,
                request_key=uuid.uuid4().hex,
                request_hash=first.request_hash,
            )
        with self.assertRaises(AppError):
            create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        foreign = Problem.objects.create(child=self.learner, created_by=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VariantDraft.objects.create(
                problem=foreign,
                text_version=first.text_version,
                payload=first.payload,
                generator=first.generator,
                intent=first.intent,
                created_by=self.a,
                request_key=uuid.uuid4().hex,
                request_hash=first.request_hash,
            )

    def test_unsupported_variant_and_unreviewed_item_cannot_create_draft(self):
        item = self.imported()
        from django.http import Http404

        with self.assertRaises(Http404):
            create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        review_source(self.reviewer, self.source.pk, "approved", "Unit check")
        item.math_spec = {"kind": "geometry_proof"}
        item.save()
        review_item(
            self.reviewer,
            item.pk,
            "approved",
            "Unit check",
            statement_checked=True,
            answer_checked=True,
            explanation_checked=True,
        )
        with self.assertRaises(AppError):
            create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)

    def test_database_rejects_draft_scope_changes_publication_and_check_rewrite(self):
        item = self.approved()
        draft = create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        for changes in [
            {"verification_status": "human_verified"},
            {"payload": {"text": "Changed"}},
            {"problem_id": uuid.uuid4()},
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                VariantDraft.objects.filter(pk=draft.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            item.checks.update(result={"result": "correct"})

    def test_database_content_edit_cannot_keep_approved_state(self):
        item = self.approved()
        QuestionBankItem.objects.filter(pk=item.pk).update(answer="0", review_status="approved")
        item.refresh_from_db()
        self.assertEqual(item.review_status, "pending")
        self.assertEqual(item.verification_status, "imported_unverified")
        self.assertEqual(item.revision, 2)

    def test_admin_workflow_templates_render_and_require_csrf_and_permissions(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        url = reverse("admin:question_bank_workflow")
        response = client.get(url)
        self.assertContains(response, "题库导入与审核工作台")
        self.assertEqual(
            client.post(url, {"operation": "preview", "payload": "{}"}).status_code, 403
        )
        self.a.is_staff = True
        self.a.save()
        client.force_login(self.a)
        self.assertEqual(client.get(url).status_code, 403)

    def test_account_deletion_cascades_private_drafts_but_keeps_shared_bank(self):
        item = self.approved()
        create_variant(self.a, self.problem.pk, self.variant(item), uuid.uuid4().hex)
        request_deletion(self.a)
        process_pending_deletions()
        self.assertEqual(VariantDraft.objects.count(), 0)
        self.assertEqual(Problem.objects.filter(pk=self.problem.pk).count(), 0)
        self.assertEqual(QuestionBankItem.objects.count(), 1)
