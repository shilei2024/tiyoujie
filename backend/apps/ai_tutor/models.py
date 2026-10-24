from django.conf import settings
from django.db import models

from apps.accounts.models import Entity, Family
from apps.problems.models import Problem


class AnalysisInput(Entity):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    job = models.OneToOneField("ocr.OCRJob", on_delete=models.CASCADE)
    student_answer = models.TextField(max_length=4000, blank=True)
    grade = models.PositiveSmallIntegerField(null=True)


class Analysis(Entity):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    job = models.OneToOneField("ocr.OCRJob", on_delete=models.CASCADE)
    payload = models.JSONField()


class AnalysisFeedback(Entity):
    analysis = models.ForeignKey(Analysis, on_delete=models.CASCADE, related_name="feedback")
    number = models.PositiveIntegerField()
    kind = models.CharField(
        max_length=16, choices=[("report", "报告问题"), ("correction", "人工修订")]
    )
    text = models.TextField(max_length=4000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["analysis", "number"], name="analysis_feedback_number")
        ]


class ServicePreference(Entity):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    billing_mode = models.CharField(
        max_length=20, choices=[("platform_trial", "平台体验"), ("byok", "我的 API")]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "family"], name="service_preference_owner")
        ]
