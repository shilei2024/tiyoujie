from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import family_for
from apps.accounts.security import rate_limit
from apps.accounts.serializers import StrictSerializer
from apps.accounts.views import family_query, validated
from apps.metering.models import BudgetPolicy, QuotaWindow, UsageLedger
from apps.metering.services import periods
from config.errors import AppError

from .models import OCRModel
from .services import cancel_scope, create_job, job_for


class JobInput(StrictSerializer):
    model_id = serializers.UUIDField()
    asset_id = serializers.UUIDField()
    billing_mode = serializers.ChoiceField(choices=["platform_trial", "byok"])
    credential_id = serializers.UUIDField(required=False, allow_null=True)
    expected_revision = serializers.IntegerField(min_value=1)
    notice_version = serializers.CharField(max_length=32)
    cost_confirmed = serializers.BooleanField()


def job_output(job):
    ledger = job.usageledger
    return {
        "id": job.pk,
        "task_type": job.task_type,
        "problem_id": job.problem_id,
        "asset_id": job.asset_id,
        "billing_mode": job.billing_mode,
        "quota_units": job.snapshot.get("quota_units", 1),
        "provider": job.snapshot["provider"],
        "model": job.snapshot["model_name"],
        "status": job.status,
        "error_code": job.error_code,
        "fee_status": ledger.status,
        "cancel_requested": job.cancel_requested,
        "input_revision": job.input_revision,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


class Models(APIView):
    def get(self, request):
        results = list(
            OCRModel.objects.filter(
                enabled=True, supports_vision=True, runtime_approved=True
            ).values(
                "id",
                "provider",
                "model_name",
                "notice",
                "notice_version",
                "max_input_bytes",
                "integration_verified",
                "ocr_quota_units",
            )
        )
        return Response({"outbound_enabled": settings.OCR_OUTBOUND_ENABLED, "results": results})


class CreateOCR(APIView):
    def get(self, request, pk):
        from apps.problems.services import problem_for

        from .models import OCRJob

        problem_for(request.user, pk)
        return Response(
            {
                "results": [
                    job_output(job)
                    for job in OCRJob.objects.filter(problem_id=pk, task_type="ocr").order_by(
                        "-created_at"
                    )[:20]
                ]
            }
        )

    def post(self, request, pk):
        rate_limit(request, "ocr")
        data = validated(JobInput, request.data)
        if not data["cost_confirmed"]:
            raise AppError("COST_CONFIRMATION_REQUIRED", "请确认本次外发服务与费用承担方式。", 400)
        result = create_job(request.user, pk, data, request.headers.get("Idempotency-Key", ""))
        return Response(job_output(result), status=202)


class Task(APIView):
    def get(self, request, pk):
        return Response(job_output(job_for(request.user, pk)))


class CancelTask(APIView):
    def post(self, request, pk):
        job = job_for(request.user, pk, manage=True)
        with transaction.atomic():
            cancel_scope(pk=job.pk)
        job.refresh_from_db()
        return Response(job_output(job))


class UsageSummary(APIView):
    def get(self, request):
        family = family_for(request.user, family_query(request))
        policy = BudgetPolicy.objects.filter(pk="base").first()
        remaining = 0
        if policy:
            day, _, _ = periods(policy, timezone.now())
            values = []
            for scope, period, limit in (
                (f"family:{family.pk}", day, policy.family_daily_quota),
                (f"family:{family.pk}", "lifetime", policy.family_total_quota),
                (f"user:{request.user.pk}", day, policy.user_daily_quota),
            ):
                quota = QuotaWindow.objects.filter(scope=scope, period=period).first()
                values.append(max(0, limit - (quota.reserved + quota.consumed if quota else 0)))
            remaining = min(values)
        query = UsageLedger.objects.filter(
            family_id=family.pk, actor_id=request.user.pk, billing_mode="byok"
        )
        return Response(
            {
                "platform_trial": {
                    "enabled": bool(
                        policy
                        and policy.platform_enabled
                        and not policy.halted
                        and (settings.OCR_OUTBOUND_ENABLED or settings.AI_ANALYSIS_ENABLED)
                        and settings.PLATFORM_AI_ENABLED
                    ),
                    "remaining_requests": remaining,
                    "remaining_units": remaining,
                    "unknown_fee_count": UsageLedger.objects.filter(
                        family_id=family.pk, billing_mode="platform_trial", status="unknown"
                    ).count(),
                },
                "byok": {
                    "usage": query.aggregate(
                        input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens")
                    ),
                    "unknown_fee_count": query.filter(status="unknown").count(),
                    "cost_is_supplier_bill": False,
                },
            }
        )
