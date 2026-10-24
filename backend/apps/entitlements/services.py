import calendar
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.accounts.access import family_for
from apps.accounts.models import Family
from apps.accounts.services import audit
from config.errors import AppError

from .models import (
    EntitlementEvent,
    EntitlementGrant,
    FamilyNotification,
    PromotionCampaign,
    ResourcePolicy,
)


def policy():
    result = ResourcePolicy.objects.filter(pk="base").first()
    if not result:
        raise AppError("SITE_NOT_CONFIGURED", "请先由管理员配置家庭与档案的基础限额。", 503)
    return result


def add_months(start, months, timezone_name):
    zone = ZoneInfo(timezone_name)
    local = start.astimezone(zone)
    year, month_index = divmod(local.year * 12 + local.month - 1 + months, 12)
    month = month_index + 1
    result = local.replace(
        year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1])
    )
    if result.replace(fold=0).utcoffset() != result.replace(fold=1).utcoffset():
        raise AppError(
            "ENTITLEMENT_TIME_AMBIGUOUS", "到期时刻存在时区歧义，请管理员调整活动。", 409
        )
    return result.astimezone(UTC)


def active_grants(family, now=None):
    now = now or timezone.now()
    return EntitlementGrant.objects.filter(
        family=family, revoked_at__isnull=True, starts_at__lte=now, expires_at__gt=now
    )


def child_limit(family, now=None):
    limits = [policy().basic_child_limit]
    for grant in active_grants(family, now):
        if "extra_child_profiles" in grant.features and grant.child_profile_limit:
            limits.append(grant.child_profile_limit)
    return max(limits)


def eligible(user, family, campaign, now):
    if campaign.status != "active" or not campaign.window_start <= now < campaign.window_end:
        return False
    if not campaign.allow_existing and not (
        campaign.window_start <= user.date_joined < campaign.window_end
        and campaign.window_start <= family.created_at < campaign.window_end
    ):
        return False
    return not EntitlementGrant.objects.filter(
        family=family, exclusivity_group=campaign.exclusivity_group
    ).exists()


@transaction.atomic
def claim(user, family_id, campaign_id):
    family_for(user, family_id, owner=True)
    family = Family.objects.select_for_update().get(pk=family_id)
    campaign = PromotionCampaign.objects.select_for_update().filter(pk=campaign_id).first()
    if not campaign:
        raise AppError("NOT_FOUND", "活动不存在。", 404)
    existing = EntitlementGrant.objects.filter(family=family, campaign=campaign).first()
    if existing:
        return existing
    now = timezone.now()
    campaign.full_clean()
    if not eligible(user, family, campaign, now):
        raise AppError("CAMPAIGN_INELIGIBLE", "当前家庭不符合活动资格。", 403)
    if (
        campaign.capacity is not None
        and EntitlementGrant.objects.filter(campaign=campaign).count() >= campaign.capacity
    ):
        raise AppError("CAMPAIGN_FULL", "活动名额已满。", 409)
    grant = EntitlementGrant.objects.create(
        family=family,
        campaign=campaign,
        features=list(campaign.features),
        child_profile_limit=campaign.child_profile_limit,
        exclusivity_group=campaign.exclusivity_group,
        starts_at=now,
        expires_at=add_months(now, campaign.duration_months, campaign.timezone_name),
    )
    EntitlementEvent.objects.create(grant=grant, kind="granted")
    audit(user, "entitlement_granted", grant, family)
    return grant


@transaction.atomic
def manual_grant(actor, family_id, campaign_id, reason):
    if (
        not actor
        or not actor.is_active
        or not actor.is_staff
        or not actor.has_perm("entitlements.add_entitlementgrant")
        or not 1 <= len(reason.strip()) <= 200
    ):
        raise AppError("FORBIDDEN", "补发需要授权操作员和有效原因。", 403)
    family = Family.objects.select_for_update().filter(pk=family_id).first()
    if not family:
        raise AppError("NOT_FOUND", "家庭不存在。", 404)
    # The ordinary eligibility, capacity and once-per-family rules also apply to operators.
    grant = claim(family.owner, family.pk, campaign_id)
    audit(actor, "entitlement_manually_issued", grant, family, reason.strip())
    return grant


def process_entitlements(now=None):
    now = now or timezone.now()
    for identifier in EntitlementGrant.objects.filter(revoked_at__isnull=True).values_list(
        "pk", flat=True
    ):
        with transaction.atomic():
            grant = (
                EntitlementGrant.objects.select_for_update()
                .select_related("campaign")
                .get(pk=identifier)
            )
            if grant.revoked_at or grant.starts_at > now:
                continue
            if grant.expires_at <= now:
                EntitlementEvent.objects.get_or_create(grant=grant, kind="expired")
                continue
            for days in set(grant.campaign.reminder_days):
                # Deliver within the node's 24-hour window, without flooding after downtime.
                when = grant.expires_at - timedelta(days=days)
                if when <= now < when + timedelta(days=1):
                    event, _ = EntitlementEvent.objects.get_or_create(
                        grant=grant, kind="reminder", node=str(days)
                    )
                    FamilyNotification.objects.get_or_create(
                        event=event,
                        defaults={
                            "family": grant.family,
                            "message": (
                                "平台功能体验将在 "
                                f"{grant.expires_at.astimezone(ZoneInfo(grant.campaign.timezone_name)).date()}"
                                " 到期；到期不自动收费，历史数据保留。"
                            ),
                        },
                    )
