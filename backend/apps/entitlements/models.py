from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import Entity, Family

FEATURES = {"advanced_reports", "bulk_management", "extended_exports", "extra_child_profiles"}


def check_features(features):
    if not isinstance(features, list) or any(
        not isinstance(x, str) or x not in FEATURES for x in features
    ):
        raise ValidationError("权益列表包含未知功能")


class ResourcePolicy(models.Model):
    key = models.CharField(primary_key=True, max_length=16, default="base", editable=False)
    basic_child_limit = models.PositiveSmallIntegerField()
    max_families = models.PositiveSmallIntegerField()


class PromotionCampaign(Entity):
    name = models.CharField(max_length=80)
    status = models.CharField(
        max_length=16,
        choices=[("draft", "草稿"), ("active", "启用"), ("paused", "暂停")],
        default="draft",
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    timezone_name = models.CharField(max_length=64, default="Asia/Shanghai")
    duration_months = models.PositiveSmallIntegerField(default=6)
    allow_existing = models.BooleanField(default=False)
    features = models.JSONField(default=list, blank=True, validators=[check_features])
    child_profile_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    reminder_days = models.JSONField(default=list, blank=True)
    exclusivity_group = models.CharField(max_length=32, default="launch_trial")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(window_end__gt=F("window_start")), name="campaign_window_valid"
            ),
            models.CheckConstraint(
                condition=Q(duration_months__gte=1, duration_months__lte=24),
                name="campaign_duration_valid",
            ),
        ]

    def clean(self):
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError("无效的活动时区") from None
        check_features(self.features)
        if not isinstance(self.reminder_days, list) or any(
            type(x) is not int or x < 0 or x > 366 for x in self.reminder_days
        ):
            raise ValidationError("提醒节点须为 0–366 的天数")
        if "extra_child_profiles" in self.features and not self.child_profile_limit:
            raise ValidationError("扩展档案权益需配置数量上限")


class EntitlementGrant(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    campaign = models.ForeignKey(PromotionCampaign, on_delete=models.PROTECT)
    features = models.JSONField(validators=[check_features])
    child_profile_limit = models.PositiveSmallIntegerField(null=True)
    exclusivity_group = models.CharField(max_length=32)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["family", "campaign"], name="grant_once_per_family"),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("starts_at")), name="grant_dates_valid"
            ),
        ]


class EntitlementEvent(Entity):
    grant = models.ForeignKey(EntitlementGrant, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    node = models.CharField(max_length=32, default="once")
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["grant", "kind", "node"], name="entitlement_event_once")
        ]


class FamilyNotification(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    event = models.OneToOneField(EntitlementEvent, on_delete=models.CASCADE)
    message = models.CharField(max_length=200)
