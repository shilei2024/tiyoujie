from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import Entity


class BudgetPolicy(models.Model):
    key = models.CharField(primary_key=True, default="base", editable=False, max_length=16)
    platform_enabled = models.BooleanField(default=False)
    alert_at_percent = models.PositiveSmallIntegerField(
        default=80, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    halted = models.BooleanField(default=False)
    currency = models.CharField(
        max_length=3, choices=[("CNY", "CNY"), ("USD", "USD")], default="CNY"
    )
    timezone_name = models.CharField(max_length=64, default="Asia/Shanghai")
    lifetime_limit = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    month_limit = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    day_limit = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    family_day_limit = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    family_daily_quota = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    family_total_quota = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    user_daily_quota = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    family_pending_limit = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    byok_daily_limit = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    def clean(self):
        try:
            ZoneInfo(self.timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValidationError("预算时区无效") from None
        if (
            not self.halted
            and UsageLedger.objects.filter(billing_mode="platform_trial", status="unknown").exists()
        ):
            raise ValidationError("未决平台费用完成对账前不能解除熔断")
        if BudgetWindow.objects.exists():
            old = BudgetPolicy.objects.filter(pk=self.pk).first()
            if old and (old.currency, old.timezone_name) != (self.currency, self.timezone_name):
                raise ValidationError("已产生账本后不能更换币种或预算时区")


class PriceVersion(Entity):
    model = models.ForeignKey("ocr.OCRModel", on_delete=models.PROTECT)
    currency = models.CharField(max_length=3, choices=[("CNY", "CNY"), ("USD", "USD")])
    # Currency micro-units per million tokens; all arithmetic is integer ceiling.
    input_per_million = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    output_per_million = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    input_token_bound = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(2000000)]
    )
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    bound_reviewed = models.BooleanField(default=False)
    evidence = models.CharField(max_length=400)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_until__gt=F("valid_from")), name="price_window_valid"
            )
        ]


class BudgetWindow(Entity):
    alerted = models.BooleanField(default=False)
    kind = models.CharField(max_length=16)
    scope = models.CharField(max_length=48)
    period = models.CharField(max_length=32)
    reserved = models.PositiveBigIntegerField(default=0)
    settled = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "scope", "period"], name="budget_window_once")
        ]


class QuotaWindow(Entity):
    scope = models.CharField(max_length=48)
    period = models.CharField(max_length=32)
    reserved = models.PositiveIntegerField(default=0)
    consumed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "period"], name="quota_window_once")
        ]


class UsageLedger(Entity):
    job = models.OneToOneField("ocr.OCRJob", on_delete=models.PROTECT)
    family_id = models.UUIDField()
    actor_id = models.PositiveIntegerField()
    billing_mode = models.CharField(max_length=20)
    provider = models.CharField(max_length=16)
    currency = models.CharField(max_length=3, blank=True)
    status = models.CharField(max_length=24, default="reserved")
    reserved_micros = models.PositiveBigIntegerField(default=0)
    settled_micros = models.PositiveBigIntegerField(null=True)
    estimated_micros = models.PositiveBigIntegerField(null=True)
    input_tokens = models.PositiveIntegerField(null=True)
    output_tokens = models.PositiveIntegerField(null=True)
    budget_window_ids = models.JSONField(default=list)
    quota_window_ids = models.JSONField(default=list)
    quota_finished = models.BooleanField(default=False)
