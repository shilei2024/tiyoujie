import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import ChildAccessGrant, FamilyMember
from apps.accounts.services import process_pending_deletions, request_deletion
from apps.practice.models import Attempt, ExportTicket, ReviewEvent, ReviewSchedule, Worksheet
from apps.practice.services import (
    INTERVALS,
    apply_review,
    cleanup_exports,
    local_today,
)
from apps.problems.services import create_problem, delete_problem, save_text
from apps.question_bank.models import QuestionBankItem, QuestionSource
from apps.question_bank.services import check_item, review_item, review_source
from tests.test_phase2 import ApiCase


def freeze(moment):
    return patch("apps.practice.services.timezone.now", return_value=moment)


class PracticeCase(ApiCase):
    def setUp(self):
        super().setUp()
        self.learner = self.child()
        self.problem = create_problem(self.a, {"child_id": self.learner.pk, "chapter": "分数"})
        save_text(
            self.a,
            self.problem.pk,
            {
                "text": "计算 1/2 + 1/3",
                "answer": "5/6",
                "confirmed": True,
                "expected_revision": self.problem.revision,
            },
        )
        self.problem.refresh_from_db()
        self.worksheet = Worksheet.objects.create(
            child=self.learner, title="周五复习", created_by=self.a
        )

    def add_problem(self, worksheet=None, problem=None):
        worksheet = worksheet or self.worksheet
        return self.client.post(
            f"/api/v1/worksheets/{worksheet.pk}/items/",
            {"origin": "problem", "problem_id": str((problem or self.problem).pk)},
            format="json",
        )

    def reviewer(self):
        return get_user_model().objects.create_superuser(username=f"r-{uuid.uuid4().hex[:6]}")

    def bank_item(self, answer="5/6", spec=None, valid_days=30):
        reviewer = self.reviewer()
        source = QuestionSource.objects.create(
            name="Synthetic licensed source",
            source_type="licensed",
            source_reference="Synthetic fixture",
            license_name="Fixture license",
            rights_evidence="Synthetic evidence",
            attribution="Fixture attribution",
            usage_conditions="Isolated test database only",
            allow_public=True,
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=valid_days),
        )
        review_source(reviewer, source.pk, "approved", "Synthetic rights checked")
        item = QuestionBankItem.objects.create(
            source=source,
            text="计算 1/2 + 1/3",
            answer=answer,
            explanation="通分后相加。",
            answer_source="Fixture",
            explanation_source="Fixture",
            grade=7,
            question_type="计算",
            solution_structure="通分",
            difficulty=1,
            knowledge_points=["rational"],
            math_spec=spec or {"kind": "arithmetic", "expression": "1/2+1/3"},
        )
        check_item(reviewer, item.pk)
        return review_item(
            reviewer,
            item.pk,
            "approved",
            "Synthetic statement and explanation checked",
            statement_checked=True,
            explanation_checked=True,
        )

    def student_client(self):
        member = FamilyMember.objects.create(user=self.student, family=self.family, role="student")
        ChildAccessGrant.objects.create(member=member, child=self.learner)
        return self.client_for(self.student)


class WorksheetTests(PracticeCase):
    def test_worksheet_requires_guardian_consent_and_valid_scope(self):
        self.assertEqual(self.add_problem().status_code, 201)
        student = self.student_client()
        response = student.post(
            "/api/v1/worksheets/",
            {"child_id": str(self.learner.pk), "title": "学生自建"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        other = self.client_for(self.b)
        self.assertEqual(
            other.get(f"/api/v1/worksheets/?child_id={self.learner.pk}").status_code, 404
        )
        self.assertEqual(self.client.get(f"/api/v1/worksheets/{uuid.uuid4()}/").status_code, 404)

    def test_item_snapshot_hides_answer_from_student_until_attempt(self):
        item = self.add_problem().json()
        self.assertNotIn("answer", item)
        student = self.student_client()
        detail = student.get(f"/api/v1/worksheets/{self.worksheet.pk}/").json()
        self.assertNotIn("answer", detail["items"][0])
        self.assertEqual(detail["items"][0]["text"], "计算 1/2 + 1/3")
        guardian = self.client.get(f"/api/v1/worksheets/{self.worksheet.pk}/").json()
        self.assertEqual(guardian["items"][0]["answer"], "5/6")

    def test_duplicate_problem_and_item_limit(self):
        self.assertEqual(self.add_problem().status_code, 201)
        self.assertEqual(self.add_problem().status_code, 409)
        for index in range(29):
            problem = create_problem(self.a, {"child_id": self.learner.pk})
            save_text(
                self.a,
                problem.pk,
                {
                    "text": f"题目 {index}",
                    "answer": "",
                    "confirmed": True,
                    "expected_revision": problem.revision,
                },
            )
            response = self.add_problem(problem=problem)
            self.assertEqual(response.status_code, 201)
        extra = create_problem(self.a, {"child_id": self.learner.pk})
        save_text(
            self.a,
            extra.pk,
            {
                "text": "第 31 题",
                "answer": "",
                "confirmed": True,
                "expected_revision": extra.revision,
            },
        )
        self.assertEqual(self.add_problem(problem=extra).status_code, 409)

    def test_unconfirmed_text_and_foreign_problem_cannot_be_added(self):
        problem = create_problem(self.a, {"child_id": self.learner.pk})
        response = self.add_problem(problem=problem)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "CONFIRMED_TEXT_REQUIRED")
        other_child = self.child(nickname="另一个孩子", family=self.other)
        other_problem = create_problem(self.b, {"child_id": other_child.pk})
        save_text(
            self.b,
            other_problem.pk,
            {
                "text": "别人的题",
                "answer": "",
                "confirmed": True,
                "expected_revision": other_problem.revision,
            },
        )
        self.assertEqual(self.add_problem(problem=other_problem).status_code, 404)

    def test_remove_item_renumbers_and_audits(self):
        first = self.add_problem().json()
        second_problem = create_problem(self.a, {"child_id": self.learner.pk})
        save_text(
            self.a,
            second_problem.pk,
            {
                "text": "第二题",
                "answer": "",
                "confirmed": True,
                "expected_revision": second_problem.revision,
            },
        )
        second = self.add_problem(problem=second_problem).json()
        self.assertEqual(second["position"], 2)
        response = self.client.delete(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/{first['id']}/"
        )
        self.assertEqual(response.status_code, 200)
        remaining = self.worksheet.items.get()
        self.assertEqual(remaining.position, 1)
        self.assertEqual(remaining.text, "第二题")

    def test_delete_worksheet_blocks_further_access_and_export(self):
        self.add_problem()
        ticket = self.client.post(
            "/api/v1/exports/",
            {
                "kind": "worksheet",
                "child_id": str(self.learner.pk),
                "worksheet_id": str(self.worksheet.pk),
            },
            format="json",
        ).json()
        self.assertEqual(self.client.get(ticket["url"]).status_code, 200)
        self.assertEqual(
            self.client.delete(
                f"/api/v1/worksheets/{self.worksheet.pk}/", {"confirm": True}, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/worksheets/{self.worksheet.pk}/").status_code, 404
        )
        self.assertEqual(self.client.get(ticket["url"]).status_code, 410)


class BankItemTests(PracticeCase):
    def test_bank_item_requires_trusted_source(self):
        item = self.bank_item()
        response = self.client.post(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/",
            {"origin": "bank", "bank_item_id": str(item.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["text"], "计算 1/2 + 1/3")

    def test_revoked_or_expired_source_hides_snapshot_and_blocks_attempt(self):
        item = self.bank_item()
        created = self.client.post(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/",
            {"origin": "bank", "bank_item_id": str(item.pk)},
            format="json",
        ).json()
        item.source.valid_until = timezone.now() - timedelta(seconds=1)
        item.source.review_status = "approved"
        item.source.save()
        detail = self.client.get(f"/api/v1/worksheets/{self.worksheet.pk}/").json()
        row = detail["items"][0]
        self.assertFalse(row["source_available"])
        self.assertNotIn("text", row)
        self.assertEqual(
            self.client.post(
                f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/",
                {"answer": "5/6", "self_grade": "correct"},
                format="json",
            ).status_code,
            409,
        )


class AttemptTests(PracticeCase):
    def test_auto_grading_ignores_self_claimed_correctness(self):
        item = self.bank_item()
        created = self.client.post(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/",
            {"origin": "bank", "bank_item_id": str(item.pk)},
            format="json",
        ).json()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        wrong = self.client.post(
            url, {"answer": "2/5", "self_grade": "correct"}, format="json"
        ).json()
        self.assertFalse(wrong["is_correct"])
        self.assertEqual(wrong["graded_by"], "auto")
        right = self.client.post(url, {"answer": "5/6", "self_grade": "wrong"}, format="json")
        self.assertTrue(right.json()["is_correct"])
        self.assertEqual(right.json()["number"], 2)

    def test_self_grading_used_when_structure_check_unsupported(self):
        created = self.add_problem().json()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        for grade, expected in [
            ("correct", True),
            ("wrong", False),
            ("unsure", None),
        ]:
            response = self.client.post(
                url, {"answer": "过程略", "self_grade": grade}, format="json"
            ).json()
            self.assertIs(response["is_correct"], expected)
            self.assertEqual(response["graded_by"], "self")

    def test_attempt_limit_and_validation(self):
        created = self.add_problem().json()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        self.assertEqual(
            self.client.post(
                url, {"answer": "x", "self_grade": "correct", "duration_seconds": -1}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                url, {"answer": "x", "self_grade": "bogus"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                url, {"answer": "x", "self_grade": "correct", "extra": 1}, format="json"
            ).status_code,
            400,
        )
        for index in range(20):
            response = self.client.post(
                url, {"answer": f"x{index}", "self_grade": "wrong"}, format="json"
            )
            self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.client.post(
                url, {"answer": "x", "self_grade": "wrong"}, format="json"
            ).status_code,
            409,
        )

    def test_student_with_grant_can_answer_but_not_manage(self):
        created = self.add_problem().json()
        student = self.student_client()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        self.assertEqual(
            student.post(url, {"answer": "", "self_grade": "unsure"}, format="json").status_code,
            201,
        )
        self.assertEqual(
            student.post(
                f"/api/v1/worksheets/{self.worksheet.pk}/items/",
                {"origin": "problem", "problem_id": str(self.problem.pk)},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            student.delete(f"/api/v1/worksheets/{self.worksheet.pk}/").status_code, 403
        )

    def test_student_without_grant_is_blocked(self):
        created = self.add_problem().json()
        student = self.client_for(self.student)
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        self.assertEqual(
            student.post(url, {"answer": "", "self_grade": "unsure"}, format="json").status_code,
            404,
        )


class ReviewScheduleTests(PracticeCase):
    def test_ladder_and_wrong_answer_reset(self):
        today = local_today()
        self.problem.refresh_from_db()
        schedule = apply_review(self.a, self.problem, "correct")
        self.assertEqual(schedule.interval_days, 1)
        self.assertEqual(schedule.due_on, today + timedelta(days=1))
        self.assertEqual(schedule.stage, "learning")
        for expected in INTERVALS[1:5]:
            schedule = apply_review(self.a, self.problem, "correct")
            self.assertEqual(schedule.interval_days, expected)
        self.assertEqual(schedule.stage, "mastered")
        schedule = apply_review(self.a, self.problem, "wrong")
        self.assertEqual((schedule.interval_days, schedule.streak, schedule.lapses), (1, 0, 1))
        self.assertEqual(schedule.due_on, today + timedelta(days=1))

    def test_review_uses_local_calendar_day(self):
        moment = datetime(2026, 10, 24, 16, 30, tzinfo=UTC)  # 2026-10-25 00:30 in UTC+8
        with freeze(moment):
            self.assertEqual(local_today(), date(2026, 10, 25))
            schedule = apply_review(self.a, self.problem, "correct")
        self.assertEqual(schedule.due_on, date(2026, 10, 26))

    def test_queue_contains_due_overdue_and_new_items(self):
        queue = self.client.get(f"/api/v1/reviews/queue/?child_id={self.learner.pk}").json()
        self.assertEqual(queue["date"], local_today().isoformat())
        self.assertEqual([row["stage"] for row in queue["results"]], ["new"])
        self.assertEqual(queue["counts"]["new"], 1)
        apply_review(self.a, self.problem, "correct")
        queue = self.client.get(f"/api/v1/reviews/queue/?child_id={self.learner.pk}").json()
        self.assertEqual(queue["results"], [])
        self.assertEqual(queue["counts"]["due"], 0)
        ReviewSchedule.objects.update(due_on=local_today() - timedelta(days=2))
        queue = self.client.get(f"/api/v1/reviews/queue/?child_id={self.learner.pk}").json()
        self.assertEqual(queue["counts"]["due"], 1)
        self.assertEqual(queue["results"][0]["overdue_days"], 2)

    def test_grade_endpoint_is_scoped_and_validated(self):
        self.assertEqual(
            self.client.post(
                f"/api/v1/problems/{self.problem.pk}/review/", {"grade": "great"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client_for(self.b)
            .post(
                f"/api/v1/problems/{self.problem.pk}/review/", {"grade": "correct"}, format="json"
            )
            .status_code,
            404,
        )
        response = self.client.post(
            f"/api/v1/problems/{self.problem.pk}/review/", {"grade": "correct"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["due_on"], (local_today() + timedelta(days=1)).isoformat())

    def test_review_events_are_append_only_and_schedule_is_unique(self):
        apply_review(self.a, self.problem, "correct")
        event = ReviewEvent.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewEvent.objects.filter(pk=event.pk).update(grade="wrong")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewSchedule.objects.create(
                child=self.learner, problem=self.problem, due_on=local_today()
            )

    def test_deleted_problem_leaves_queue_and_schedule(self):
        apply_review(self.a, self.problem, "correct")
        delete_problem(self.a, self.problem.pk)
        queue = self.client.get(f"/api/v1/reviews/queue/?child_id={self.learner.pk}").json()
        self.assertEqual(queue["results"], [])
        self.assertEqual(ReviewSchedule.objects.count(), 0)


class TrendTests(PracticeCase):
    def test_sample_threshold_and_weekly_buckets(self):
        created = self.add_problem().json()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        self.client.post(url, {"answer": "a", "self_grade": "correct"}, format="json")
        data = self.client.get(f"/api/v1/children/{self.learner.pk}/trends/").json()
        self.assertEqual(data["sample"]["attempts"], 1)
        self.assertFalse(data["sample"]["sufficient"])
        self.assertEqual(len(data["weeks"]), 8)
        self.assertEqual(sum(bucket["attempts"] for bucket in data["weeks"]), 1)
        self.assertEqual(sum(bucket["problems_added"] for bucket in data["weeks"]), 1)
        self.assertEqual(data["knowledge_points"], [])
        for index in range(9):
            self.client.post(url, {"answer": str(index), "self_grade": "correct"}, format="json")
        data = self.client.get(f"/api/v1/children/{self.learner.pk}/trends/?weeks=4").json()
        self.assertEqual(data["sample"]["attempts"], 10)
        self.assertTrue(data["sample"]["sufficient"])
        self.assertEqual(len(data["weeks"]), 4)

    def test_knowledge_point_accuracy_needs_enough_samples(self):
        self.problem.knowledge_points = ["有理数"]
        self.problem.save()
        created = self.add_problem().json()
        url = f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/"
        self.client.post(url, {"answer": "a", "self_grade": "correct"}, format="json")
        data = self.client.get(f"/api/v1/children/{self.learner.pk}/trends/").json()
        point = data["knowledge_points"][0]
        self.assertEqual((point["code"], point["attempts"]), ("有理数", 1))
        self.assertIsNone(point["accuracy"])
        self.assertTrue(point["insufficient_sample"])
        for index in range(4):
            self.client.post(url, {"answer": str(index), "self_grade": "wrong"}, format="json")
        data = self.client.get(f"/api/v1/children/{self.learner.pk}/trends/").json()
        point = data["knowledge_points"][0]
        self.assertEqual(point["accuracy"], 0.2)
        self.assertFalse(point["insufficient_sample"])

    def test_trends_rejects_foreign_child(self):
        self.assertEqual(
            self.client_for(self.b).get(f"/api/v1/children/{self.learner.pk}/trends/").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/v1/children/not-a-uuid/trends/").status_code, 404)


class ExportTests(PracticeCase):
    def ticket(self, kind="worksheet", **extra):
        body = {"kind": kind, "child_id": str(self.learner.pk), **extra}
        return self.client.post("/api/v1/exports/", body, format="json")

    def test_worksheet_html_escapes_content_and_loads_no_external_resource(self):
        created = self.add_problem().json()
        self.client.post(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/",
            {"answer": "x", "self_grade": "wrong"},
            format="json",
        )
        self.worksheet.title = "<script>alert(1)</script>"
        self.worksheet.save(update_fields=["title"])
        response = self.ticket(worksheet_id=str(self.worksheet.pk))
        self.assertEqual(response.status_code, 201)
        body = self.client.get(response.json()["url"])
        self.assertEqual(body.status_code, 200)
        self.assertIn("text/html", body["Content-Type"])
        text = body.content.decode()
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertIn("Content-Security-Policy", text)
        self.assertEqual(body["Cache-Control"], "no-store")

    def test_worksheet_csv_export_and_format_validation(self):
        self.add_problem()
        response = self.ticket(worksheet_id=str(self.worksheet.pk))
        url = response.json()["url"]
        body = self.client.get(url + "?file=csv")
        self.assertEqual(body.status_code, 200)
        self.assertIn("text/csv", body["Content-Type"])
        text = body.content.decode()
        self.assertTrue(text.startswith("\ufeff"))
        self.assertIn("题号,题目,答案", text)
        self.assertIn("5/6", text)
        self.assertEqual(self.client.get(url + "?file=pdf").status_code, 400)

    def test_summary_csv_is_bom_encoded_and_formula_neutralised(self):
        self.learner.nickname = "=cmd|' /C calc'!A0"
        self.learner.save()
        self.add_problem()
        response = self.ticket(kind="summary")
        body = self.client.get(response.json()["url"])
        self.assertEqual(body.status_code, 200)
        self.assertIn("text/csv", body["Content-Type"])
        text = body.content.decode()
        self.assertTrue(text.startswith("\ufeff"))
        self.assertIn("'=cmd", text)
        self.assertIn("样本", text)

    def test_ticket_expiry_revocation_and_scope(self):
        self.add_problem()
        response = self.ticket(worksheet_id=str(self.worksheet.pk))
        url = response.json()["url"]
        self.assertEqual(self.client_for(self.b).get(url).status_code, 404)
        student = self.student_client()
        self.assertEqual(
            student.post(
                "/api/v1/exports/",
                {"kind": "summary", "child_id": str(self.learner.pk)},
                format="json",
            ).status_code,
            403,
        )
        expired = ExportTicket.objects.create(
            kind="worksheet",
            child=self.learner,
            worksheet=self.worksheet,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.client.get(f"/api/v1/exports/{expired.nonce}/").status_code, 410)
        ExportTicket.objects.filter(nonce=response.json()["nonce"]).update(
            revoked_at=timezone.now()
        )
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_export_requires_matching_worksheet_and_child(self):
        other_child = self.child(nickname="另一个", family=self.family)
        self.assertEqual(
            self.ticket(
                worksheet_id=str(self.worksheet.pk), child_id=str(other_child.pk)
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/exports/",
                {"kind": "worksheet", "child_id": str(self.learner.pk)},
                format="json",
            ).status_code,
            400,
        )

    def test_cleanup_removes_only_stale_tickets(self):
        self.add_problem()
        live = ExportTicket.objects.create(
            kind="summary",
            child=self.learner,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        stale = ExportTicket.objects.create(
            kind="summary",
            child=self.learner,
            expires_at=timezone.now() - timedelta(days=2),
        )
        cleanup_exports()
        self.assertTrue(ExportTicket.objects.filter(pk=live.pk).exists())
        self.assertFalse(ExportTicket.objects.filter(pk=stale.pk).exists())


class LedgerGuardTests(PracticeCase):
    def test_database_rejects_attempt_mutation_and_item_rebinding(self):
        created = self.add_problem().json()
        self.client.post(
            f"/api/v1/worksheets/{self.worksheet.pk}/items/{created['id']}/attempts/",
            {"answer": "x", "self_grade": "correct"},
            format="json",
        )
        attempt = Attempt.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attempt.objects.filter(pk=attempt.pk).update(self_grade="wrong")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.worksheet.items.update(text="改写后的题目")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExportTicket.objects.create(
                kind="summary", child=self.learner, expires_at=timezone.now()
            )
            ExportTicket.objects.update(nonce="forged")

    def test_account_deletion_removes_private_practice_data(self):
        self.add_problem()
        apply_review(self.a, self.problem, "correct")
        ExportTicket.objects.create(
            kind="summary",
            child=self.learner,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        request_deletion(self.a)
        process_pending_deletions()
        self.assertFalse(Worksheet.objects.exists())
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(ReviewSchedule.objects.exists())
        self.assertFalse(ExportTicket.objects.exists())
