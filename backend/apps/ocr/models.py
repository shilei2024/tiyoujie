from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.accounts.models import Entity


class OCRModel(Entity):
    provider = models.CharField(max_length=16, choices=[("deepseek", "DeepSeek"), ("kimi", "Kimi")])
    model_name = models.CharField(
        max_length=80, validators=[RegexValidator(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")]
    )
    enabled = models.BooleanField(default=False)
    supports_vision = models.BooleanField(default=False)
    supports_text = models.BooleanField(default=False)
    supports_json = models.BooleanField(default=False)
    analysis_enabled = models.BooleanField(default=False)
    ocr_quota_units = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(20)]
    )
    analysis_quota_units = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(20)]
    )
    runtime_approved = models.BooleanField(default=False)
    integration_verified = models.BooleanField(default=False)
    max_input_bytes = models.PositiveIntegerField(
        default=8388608, validators=[MinValueValidator(1), MaxValueValidator(8388608)]
    )
    max_output_tokens = models.PositiveIntegerField(
        default=2048, validators=[MinValueValidator(128), MaxValueValidator(8192)]
    )
    notice_version = models.CharField(max_length=32)
    notice = models.CharField(max_length=1500)
    official_source = models.URLField(max_length=400)


class OCRJob(Entity):
    task_type = models.CharField(
        max_length=16, default="ocr", choices=[("ocr", "图片转录"), ("analysis", "错题分析")]
    )
    actor_id = models.PositiveIntegerField()
    family_id = models.UUIDField()
    child_id = models.UUIDField()
    problem = models.ForeignKey("problems.Problem", null=True, on_delete=models.SET_NULL)
    asset = models.ForeignKey("problems.Asset", null=True, on_delete=models.SET_NULL)
    text_version = models.ForeignKey(
        "problems.ProblemTextVersion", null=True, on_delete=models.SET_NULL
    )
    model = models.ForeignKey(OCRModel, on_delete=models.PROTECT)
    price = models.ForeignKey("metering.PriceVersion", null=True, on_delete=models.PROTECT)
    billing_mode = models.CharField(
        max_length=20, choices=[("platform_trial", "平台体验"), ("byok", "我的 API")]
    )
    credential_id = models.UUIDField(null=True)
    credential_version = models.PositiveIntegerField(null=True)
    profile_consent_id = models.UUIDField()
    provider_consent_id = models.UUIDField()
    input_revision = models.PositiveIntegerField()
    input_sha256 = models.CharField(max_length=64)
    snapshot = models.JSONField()
    price_snapshot = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default="queued")
    error_code = models.CharField(max_length=48, blank=True)
    lease_token = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    sent_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    reservation_until = models.DateTimeField(null=True)
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor_id", "idempotency_key"], name="ocr_idempotency_once"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        billing_mode="platform_trial",
                        credential_id__isnull=True,
                        credential_version__isnull=True,
                    )
                    | Q(
                        billing_mode="byok",
                        credential_id__isnull=False,
                        credential_version__isnull=False,
                    )
                ),
                name="ocr_credential_mode_binding",
            ),
        ]


class Outbox(Entity):
    job = models.OneToOneField(OCRJob, on_delete=models.CASCADE)
    last_published_at = models.DateTimeField(null=True)
