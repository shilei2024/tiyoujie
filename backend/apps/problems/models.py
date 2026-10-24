from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import ChildProfile, Entity


class Problem(Entity):
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=120, blank=True)
    chapter = models.CharField(max_length=64, blank=True)
    knowledge_points = models.JSONField(default=list, blank=True)
    error_type = models.CharField(max_length=32, blank=True)
    mistake_date = models.DateField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    current_text = models.ForeignKey(
        "ProblemTextVersion", null=True, on_delete=models.SET_NULL, related_name="current_for"
    )
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=["child", "deleted_at", "created_at", "id"])]


class ProblemTextVersion(Entity):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="text_versions")
    number = models.PositiveIntegerField()
    origin = models.CharField(max_length=12, choices=[("manual", "人工"), ("ocr", "OCR 候选")])
    text = models.TextField(max_length=20000)
    answer = models.TextField(max_length=10000, blank=True)
    confirmed = models.BooleanField(default=False)
    parent = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    ocr_job_id = models.UUIDField(null=True, unique=True)
    confidence = models.FloatField(null=True)
    uncertainties = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["problem", "number"], name="text_number")]


class StoredObject(Entity):
    # Survives domain cascades so file cleanup remains recoverable after account deletion.
    family_id = models.UUIDField()
    child_id = models.UUIDField()
    object_key = models.CharField(max_length=80, unique=True)
    byte_size = models.PositiveIntegerField()
    state = models.CharField(max_length=16, default="staged")


class Asset(Entity):
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE)
    object = models.OneToOneField(StoredObject, on_delete=models.PROTECT)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    parent = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
    transform = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(width__gt=0, height__gt=0), name="asset_dimensions_positive"
            )
        ]


class ProblemAsset(Entity):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="asset_links")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="problem_links")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["problem", "asset"], name="asset_link_once")]

    def clean(self):
        if self.problem.child_id != self.asset.child_id:
            raise ValidationError("题目与图片归属不一致")
