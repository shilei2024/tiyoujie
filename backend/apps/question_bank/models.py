import hashlib
import json
import unicodedata

from django.conf import settings
from django.db import models

from apps.accounts.models import Entity


def digest(data):
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fingerprint(text):
    # Retain punctuation/signs: minus signs, units and brackets change the problem.
    return digest(" ".join(unicodedata.normalize("NFKC", text).split()))


class KnowledgePoint(models.Model):
    code = models.SlugField(primary_key=True, max_length=48)
    name = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code}: {self.name}"


class QuestionSource(Entity):
    name = models.CharField(max_length=120)
    source_type = models.CharField(
        max_length=24,
        choices=[
            (v, label)
            for v, label in [
                ("original", "原创"),
                ("licensed", "已获授权"),
                ("open_license", "开放许可"),
                ("reviewed_public", "已审核公开材料"),
                ("user_upload", "用户上传"),
                ("unknown", "未知"),
            ]
        ],
    )
    source_reference = models.CharField(max_length=500)
    license_name = models.CharField(max_length=120)
    rights_evidence = models.TextField(max_length=4000)
    attribution = models.CharField(max_length=500)
    usage_conditions = models.TextField(max_length=2000)
    allow_public = models.BooleanField(default=False)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    revision = models.PositiveIntegerField(default=1, editable=False)
    review_status = models.CharField(max_length=16, default="pending", editable=False)
    reviewed_digest = models.CharField(max_length=64, blank=True, editable=False)
    reviewed_at = models.DateTimeField(null=True, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False
    )
    review_reason = models.CharField(max_length=500, blank=True, editable=False)

    def content_digest(self):
        return digest(
            {
                name: str(getattr(self, name))
                for name in [
                    "name",
                    "source_type",
                    "source_reference",
                    "license_name",
                    "rights_evidence",
                    "attribution",
                    "usage_conditions",
                    "allow_public",
                    "valid_from",
                    "valid_until",
                ]
            }
        )

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first()
        if old and old.content_digest() != self.content_digest():
            self.revision = old.revision + 1
            self.review_status, self.reviewed_digest = "pending", ""
            self.reviewed_at, self.reviewed_by = None, None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class QuestionBankItem(Entity):
    source = models.ForeignKey(QuestionSource, on_delete=models.PROTECT)
    text = models.TextField(max_length=4000)
    answer = models.CharField(max_length=1000)
    explanation = models.TextField(max_length=4000)
    answer_source = models.CharField(max_length=500)
    explanation_source = models.CharField(max_length=500)
    grade = models.PositiveSmallIntegerField()
    question_type = models.CharField(max_length=48)
    solution_structure = models.CharField(max_length=64)
    difficulty = models.PositiveSmallIntegerField()
    knowledge_points = models.JSONField(default=list)
    math_spec = models.JSONField(default=dict, blank=True)
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    content_hash = models.CharField(max_length=64, editable=False)
    revision = models.PositiveIntegerField(default=1, editable=False)
    review_status = models.CharField(max_length=16, default="pending", editable=False)
    verification_status = models.CharField(
        max_length=32, default="imported_unverified", editable=False
    )
    verification_method = models.CharField(max_length=64, blank=True, editable=False)
    verified_at = models.DateTimeField(null=True, editable=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="bank_verifications",
        editable=False,
    )
    reviewed_hash = models.CharField(max_length=64, blank=True, editable=False)
    reviewed_source_revision = models.PositiveIntegerField(null=True, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="bank_reviews",
        editable=False,
    )
    reviewed_at = models.DateTimeField(null=True, editable=False)
    review_reason = models.CharField(max_length=500, blank=True, editable=False)

    class Meta:
        permissions = [("review_bank", "审核题库来源、数学答案及发布状态")]
        indexes = [models.Index(fields=["review_status", "grade", "difficulty"])]

    def content_data(self):
        return {
            name: getattr(self, name)
            for name in [
                "text",
                "answer",
                "explanation",
                "answer_source",
                "explanation_source",
                "grade",
                "question_type",
                "solution_structure",
                "difficulty",
                "knowledge_points",
                "math_spec",
            ]
        } | {"source_id": str(self.source_id)}

    def content_digest(self):
        return digest(self.content_data())

    def save(self, *args, **kwargs):
        self.fingerprint, self.content_hash = fingerprint(self.text), self.content_digest()
        old = type(self).objects.filter(pk=self.pk).first()
        if old and old.content_hash != self.content_hash:
            self.revision = old.revision + 1
            self.review_status, self.reviewed_hash = "pending", ""
            self.verification_status, self.verification_method = "imported_unverified", ""
            self.verified_at, self.verified_by = None, None
            self.reviewed_at, self.reviewed_by = None, None
            self.reviewed_source_revision = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{str(self.pk)[:8]} · {self.text[:40]}"


class VerificationRecord(Entity):
    item = models.ForeignKey(QuestionBankItem, on_delete=models.CASCADE, related_name="checks")
    revision = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64)
    result = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)


class VariantDraft(Entity):
    problem = models.ForeignKey("problems.Problem", on_delete=models.CASCADE)
    text_version = models.ForeignKey("problems.ProblemTextVersion", on_delete=models.CASCADE)
    bank_item_id = models.UUIDField(null=True)
    bank_revision = models.PositiveIntegerField(null=True)
    intent = models.CharField(max_length=24)
    payload = models.JSONField()
    generator = models.CharField(max_length=64)
    verification_status = models.CharField(max_length=32, default="generated_unverified")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    request_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["problem", "request_key"], name="variant_request_once")
        ]
