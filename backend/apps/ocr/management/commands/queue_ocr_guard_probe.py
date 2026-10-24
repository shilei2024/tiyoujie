import io
import json
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import ChildProfile, GuardianConsent
from apps.accounts.services import create_family
from apps.entitlements.models import ResourcePolicy
from apps.metering.models import BudgetPolicy, BudgetWindow, PriceVersion, QuotaWindow, UsageLedger
from apps.ocr.models import OCRJob, OCRModel
from apps.ocr.services import create_job
from apps.problems.services import cleanup_objects, create_problem, save_text, storage, upload_asset


class Command(BaseCommand):
    help = "Actual isolated worker must block OCR before external dispatch and refund reservations."

    def add_arguments(self, parser):
        parser.add_argument("--task-type", choices=["ocr", "analysis"], default="ocr")

    def handle(self, *args, **options):
        kind = options["task_type"]
        if (
            settings.APP_ENV != "test"
            or settings.OCR_OUTBOUND_ENABLED
            or settings.AI_ANALYSIS_ENABLED
        ):
            raise CommandError("Requires isolated test environment with outbound disabled")
        call_command("migrate", interactive=False, verbosity=0)
        ResourcePolicy.objects.get_or_create(
            key="base", defaults={"basic_child_limit": 3, "max_families": 3}
        )
        BudgetPolicy.objects.get_or_create(
            key="base",
            defaults={
                "platform_enabled": True,
                "lifetime_limit": 10000000,
                "month_limit": 10000000,
                "day_limit": 10000000,
                "family_day_limit": 10000000,
                "family_daily_quota": 3,
                "family_total_quota": 3,
                "user_daily_quota": 3,
            },
        )
        user = get_user_model().objects.create_user(username="queue-guard-" + uuid.uuid4().hex)
        model, price, job, object_key = None, None, None, None
        family = None
        try:
            family = create_family(user, "isolated queue guard")
            child = ChildProfile.objects.create(family=family, nickname="synthetic")
            for scope in ("profile", "kimi"):
                GuardianConsent.objects.create(
                    child=child,
                    guardian=user,
                    scope=scope,
                    notice_version=settings.GUARDIAN_NOTICE_VERSION,
                )
            problem = create_problem(user, {"child_id": child.pk})
            if kind == "analysis":
                problem = save_text(
                    user,
                    problem.pk,
                    {
                        "text": "Synthetic 1+1",
                        "answer": "",
                        "expected_revision": 1,
                        "confirmed": True,
                    },
                )
            buffer = io.BytesIO()
            Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
            asset = upload_asset(
                user,
                problem.pk,
                SimpleUploadedFile("synthetic.png", buffer.getvalue(), content_type="image/png"),
            )
            object_key = asset.object.object_key
            model = OCRModel.objects.create(
                provider="kimi",
                model_name="synthetic-guard-no-inference",
                enabled=True,
                supports_vision=True,
                supports_text=True,
                supports_json=True,
                analysis_enabled=True,
                runtime_approved=True,
                notice="Test-only; no provider call is permitted.",
                notice_version="guard-v1",
            )
            price = PriceVersion.objects.create(
                model=model,
                currency="CNY",
                input_per_million=1000000,
                output_per_million=1000000,
                input_token_bound=1000,
                valid_from=timezone.now() - timedelta(hours=1),
                valid_until=timezone.now() + timedelta(hours=1),
                bound_reviewed=True,
                evidence="Synthetic queue guard, not a supplier price",
            )
            problem.refresh_from_db()
            # Only the producer is enabled. The separate Linux worker remains disabled.
            with override_settings(
                OCR_OUTBOUND_ENABLED=True,
                AI_ANALYSIS_ENABLED=True,
                PLATFORM_AI_ENABLED=True,
                PLATFORM_OCR_CONFIGURED_PROVIDERS={"kimi"},
            ):
                job = create_job(
                    user,
                    problem.pk,
                    {
                        "asset_id": asset.pk,
                        "text_version_id": problem.current_text_id,
                        "student_answer": "",
                        "model_id": model.pk,
                        "expected_revision": problem.revision,
                        "billing_mode": "platform_trial",
                        "notice_version": "guard-v1",
                    },
                    uuid.uuid4().hex,
                    task_type=kind,
                )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                job.refresh_from_db()
                if job.status != "queued":
                    break
                time.sleep(0.2)
            ledger = UsageLedger.objects.get(job=job)
            budget_ids, quota_ids = ledger.budget_window_ids, ledger.quota_window_ids
            passed = (
                job.status == "failed"
                and job.error_code == ("OCR_DISABLED" if kind == "ocr" else "AI_DISABLED")
                and job.sent_at is None
                and ledger.status == "not_sent"
                and BudgetWindow.objects.filter(pk__in=budget_ids).count() == 4
                and QuotaWindow.objects.filter(pk__in=quota_ids).count() == 3
                and all(
                    w.reserved == 0 and w.settled == 0
                    for w in BudgetWindow.objects.filter(pk__in=budget_ids)
                )
                and all(
                    w.reserved == 0 and w.consumed == 0
                    for w in QuotaWindow.objects.filter(pk__in=quota_ids)
                )
            )
            if not passed:
                raise CommandError("Worker guard or reservation refund failed")
            self.stdout.write(
                json.dumps(
                    {
                        "status": "passed",
                        "task_type": kind,
                        "job_id": str(job.pk),
                        "worker_outcome": job.error_code,
                        "sent_at": None,
                        "budget_windows": len(budget_ids),
                        "quota_windows": len(quota_ids),
                    }
                )
            )
        finally:
            if job:
                UsageLedger.objects.filter(job=job).delete()
                OCRJob.objects.filter(pk=job.pk).delete()
            if family:
                family.delete()
            user.delete()
            if price:
                price.delete()
            if model:
                model.delete()
            cleanup_objects()
            if object_key and storage().path(object_key).exists():
                raise CommandError("Probe image cleanup failed")
