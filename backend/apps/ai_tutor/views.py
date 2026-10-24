from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import family_for, member_for
from apps.accounts.security import rate_limit
from apps.accounts.serializers import StrictSerializer
from apps.accounts.services import audit
from apps.accounts.views import family_query, page, validated
from apps.ocr.models import OCRJob, OCRModel
from apps.ocr.services import create_job
from apps.ocr.views import job_output
from apps.problems.services import problem_for
from config.errors import AppError

from .models import Analysis, AnalysisFeedback, ServicePreference
from .schema import JSON_SCHEMA
from .services import add_feedback


class Schema(APIView):
    def get(self, request):
        return Response(JSON_SCHEMA)


class AnalysisInputSerializer(StrictSerializer):
    model_id = serializers.UUIDField()
    text_version_id = serializers.UUIDField()
    billing_mode = serializers.ChoiceField(choices=["platform_trial", "byok"])
    credential_id = serializers.UUIDField(required=False, allow_null=True)
    expected_revision = serializers.IntegerField(min_value=1)
    student_answer = serializers.CharField(
        max_length=4000, allow_blank=True, default="", trim_whitespace=False
    )
    notice_version = serializers.CharField(max_length=32)
    cost_confirmed = serializers.BooleanField()


class FeedbackInput(StrictSerializer):
    kind = serializers.ChoiceField(choices=["report", "correction"])
    text = serializers.CharField(max_length=4000)


class PreferenceInput(StrictSerializer):
    billing_mode = serializers.ChoiceField(choices=["platform_trial", "byok"])


class FeedbackOutput(serializers.ModelSerializer):
    class Meta:
        model = AnalysisFeedback
        fields = ["id", "number", "kind", "text", "created_at"]


class AnalysisOutput(serializers.ModelSerializer):
    task = serializers.SerializerMethodField()
    text_version_id = serializers.UUIDField(source="job.text_version_id", allow_null=True)
    text_version_number = serializers.IntegerField(
        source="job.text_version.number", allow_null=True
    )
    stale = serializers.SerializerMethodField()
    reported = serializers.SerializerMethodField()

    def get_task(self, item):
        return job_output(item.job)

    def get_stale(self, item):
        return item.problem.current_text_id != item.job.text_version_id

    def get_reported(self, item):
        return item.feedback.filter(kind="report").exists()

    class Meta:
        model = Analysis
        fields = [
            "id",
            "created_at",
            "payload",
            "task",
            "text_version_id",
            "text_version_number",
            "stale",
            "reported",
        ]


class Models(APIView):
    def get(self, request):
        models = OCRModel.objects.filter(
            enabled=True,
            runtime_approved=True,
            analysis_enabled=True,
            supports_text=True,
            supports_json=True,
        )
        return Response(
            {
                "outbound_enabled": settings.AI_ANALYSIS_ENABLED,
                "results": list(
                    models.values(
                        "id",
                        "provider",
                        "model_name",
                        "notice",
                        "notice_version",
                        "integration_verified",
                        "analysis_quota_units",
                    )
                ),
            }
        )


class Jobs(APIView):
    def get(self, request, pk):
        problem_for(request.user, pk)
        jobs = OCRJob.objects.filter(problem_id=pk, task_type="analysis").order_by("-created_at")[
            :20
        ]
        return Response({"results": [job_output(job) for job in jobs]})

    def post(self, request, pk):
        rate_limit(request, "ai_analysis")
        data = validated(AnalysisInputSerializer, request.data)
        if not data["cost_confirmed"]:
            raise AppError("COST_CONFIRMATION_REQUIRED", "请确认本次服务与费用承担方式。", 400)
        job = create_job(
            request.user, pk, data, request.headers.get("Idempotency-Key", ""), task_type="analysis"
        )
        return Response(job_output(job), status=202)


class Results(APIView):
    def get(self, request, pk):
        problem_for(request.user, pk)
        query = (
            Analysis.objects.filter(problem_id=pk)
            .select_related("problem", "job__text_version")
            .order_by("-created_at", "-id")
        )
        return page(request, query, AnalysisOutput)


class Feedback(APIView):
    def get(self, request, pk):
        analysis = get_object_or_404(Analysis, pk=pk)
        problem_for(request.user, analysis.problem_id)
        return page(request, analysis.feedback.order_by("-number"), FeedbackOutput)

    def post(self, request, pk):
        rate_limit(request, "ai_feedback")
        result = add_feedback(request.user, pk, validated(FeedbackInput, request.data))
        return Response(FeedbackOutput(result).data, status=201)


class Preference(APIView):
    def scope(self, request):
        family = family_for(request.user, family_query(request))
        if member_for(request.user, family.pk).role != "guardian":
            raise AppError("FORBIDDEN", "仅监护人可以设置服务偏好。", 403)
        return family

    def get(self, request):
        family = self.scope(request)
        item = ServicePreference.objects.filter(user=request.user, family=family).first()
        return Response({"billing_mode": item.billing_mode if item else None})

    @transaction.atomic
    def post(self, request):
        family = self.scope(request)
        data = validated(PreferenceInput, request.data)
        item, _ = ServicePreference.objects.update_or_create(
            user=request.user, family=family, defaults=data
        )
        audit(request.user, "ai_preference_changed", item, family)
        return Response({"billing_mode": item.billing_mode})
