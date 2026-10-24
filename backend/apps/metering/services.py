from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.accounts.services import audit
from config.errors import AppError

from .models import BudgetPolicy, BudgetWindow, QuotaWindow, UsageLedger


def locked_policy(required=True):
    policy = BudgetPolicy.objects.select_for_update().filter(pk="base").first()
    if not policy and required:
        raise AppError("METERING_NOT_CONFIGURED", "OCR 限额尚未配置。", 503)
    return policy


def periods(policy, now):
    local = now.astimezone(ZoneInfo(policy.timezone_name))
    day_end = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    month_end = local.replace(
        year=local.year + (local.month == 12),
        month=local.month % 12 + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return (
        local.date().isoformat(),
        local.strftime("%Y-%m"),
        min(day_end, month_end).astimezone(UTC),
    )


def cost(price, input_tokens, output_tokens):
    return (
        input_tokens * price["input_per_million"]
        + output_tokens * price["output_per_million"]
        + 999999
    ) // 1000000


def reserve(job, policy, now):
    day, month, window_end = periods(policy, now)
    ledger = UsageLedger(
        job=job,
        family_id=job.family_id,
        actor_id=job.actor_id,
        billing_mode=job.billing_mode,
        provider=job.snapshot["provider"],
        currency=job.price_snapshot.get("currency", ""),
    )
    if job.billing_mode == "byok":
        ledger.status = "byok_pending"
        ledger.save()
        return
    units = job.snapshot.get("quota_units", 1)
    if type(units) is not int or not 1 <= units <= 20:
        raise AppError("QUOTA_NOT_CONFIGURED", "任务体验点数配置无效。", 503)
    if window_end - now <= timedelta(seconds=90):
        raise AppError("BUDGET_WINDOW_CHANGING", "预算周期即将切换，请稍后重试。", 429)
    if job.price.valid_until - now <= timedelta(seconds=60):
        raise AppError("PRICE_NOT_CONFIGURED", "价格版本即将到期，请管理员核对。", 503)
    job.reservation_until = min(
        window_end - timedelta(seconds=60),
        now + timedelta(minutes=10),
        job.price.valid_until - timedelta(seconds=30),
    )
    job.save(update_fields=["reservation_until"])
    upper = cost(
        job.price_snapshot,
        job.price_snapshot["input_token_bound"],
        job.snapshot["max_output_tokens"],
    )
    if upper > 10**15:
        raise AppError("PRICE_NOT_CONFIGURED", "费用上界超出支持范围，请核对价格。", 503)
    windows = [
        ("lifetime", "global", "lifetime", policy.lifetime_limit),
        ("month", "global", month, policy.month_limit),
        ("day", "global", day, policy.day_limit),
        ("family_day", str(job.family_id), day, policy.family_day_limit),
    ]
    for kind, scope, period, limit in windows:
        window, _ = BudgetWindow.objects.get_or_create(kind=kind, scope=scope, period=period)
        if window.reserved + window.settled + upper > limit:
            raise AppError("BUDGET_EXHAUSTED", "平台预算不足，请等待或明确选择自己的 API。", 403)
        window.reserved += upper
        window.save(update_fields=["reserved"])
        if (
            not window.alerted
            and (window.reserved + window.settled) * 100 >= limit * policy.alert_at_percent
        ):
            window.alerted = True
            window.save(update_fields=["alerted"])
            audit(
                None,
                "platform_budget_warning",
                window,
                reason=f"{kind}: reserved plus settled reached configured warning threshold",
            )
        ledger.budget_window_ids.append(str(window.pk))
    for scope, period, limit in (
        (f"family:{job.family_id}", "lifetime", policy.family_total_quota),
        (f"family:{job.family_id}", day, policy.family_daily_quota),
        (f"user:{job.actor_id}", day, policy.user_daily_quota),
    ):
        quota, _ = QuotaWindow.objects.get_or_create(scope=scope, period=period)
        if quota.reserved + quota.consumed + units > limit:
            raise AppError(
                "QUOTA_EXHAUSTED", "平台体验次数已用完，请等待或明确选择自己的 API。", 403
            )
        quota.reserved += units
        quota.save(update_fields=["reserved"])
        ledger.quota_window_ids.append(str(quota.pk))
    ledger.reserved_micros = upper
    ledger.save()


def finish_quota(ledger, success):
    if ledger.quota_finished:
        return
    units = ledger.job.snapshot.get("quota_units", 1)
    for quota in (
        QuotaWindow.objects.select_for_update()
        .filter(pk__in=ledger.quota_window_ids)
        .order_by("id")
    ):
        if quota.reserved < units:
            raise AppError("LEDGER_INCONSISTENT", "额度记录需管理员核对。", 503)
        quota.reserved -= units
        quota.consumed += units if success else 0
        quota.save(update_fields=["reserved", "consumed"])
    ledger.quota_finished = True


def finish(job, *, success=False, usage=None, definitely_unsent=False):
    policy = locked_policy()
    ledger = UsageLedger.objects.select_for_update().get(job=job)
    previous_status = ledger.status
    if ledger.status in {"settled", "not_sent", "byok_usage_known"}:
        return
    finish_quota(ledger, success)
    if definitely_unsent:
        ledger.status = "not_sent"
        ledger.settled_micros = 0 if job.billing_mode == "platform_trial" else None
        amount = 0
    elif usage:
        ledger.input_tokens, ledger.output_tokens = usage
        amount = cost(job.price_snapshot, *usage) if job.price_snapshot else None
        if job.billing_mode == "byok":
            ledger.estimated_micros = amount
            ledger.status = "byok_usage_known"
        else:
            ledger.settled_micros = amount
            ledger.status = "settled"
            if (
                amount > ledger.reserved_micros
                or usage[0] > job.price_snapshot["input_token_bound"]
                or usage[1] > job.snapshot["max_output_tokens"]
            ):
                policy.halted = True
                policy.save(update_fields=["halted"])
                audit(
                    None,
                    "platform_bound_exceeded",
                    job,
                    reason="Usage exceeded reviewed upper bound",
                )
    else:
        ledger.status = "unknown"
        amount = None
        if job.billing_mode == "platform_trial":
            policy.halted = True
            policy.save(update_fields=["halted"])
            if previous_status != "unknown":
                audit(
                    None,
                    "platform_cost_unknown",
                    job,
                    reason="Supplier usage unconfirmed; reservation held; automatic retry disabled",
                )
    if job.billing_mode == "platform_trial" and amount is not None:
        for window in (
            BudgetWindow.objects.select_for_update()
            .filter(pk__in=ledger.budget_window_ids)
            .order_by("id")
        ):
            if window.reserved < ledger.reserved_micros:
                raise AppError("LEDGER_INCONSISTENT", "预算记录需管理员核对。", 503)
            window.reserved -= ledger.reserved_micros
            window.settled += amount
            window.save(update_fields=["reserved", "settled"])
    ledger.save()


@transaction.atomic
def reconcile(actor, job, amount, reason):
    if (
        not actor.is_active
        or not actor.is_staff
        or not actor.has_perm("metering.change_budgetpolicy")
        or not 1 <= len(reason.strip()) <= 200
    ):
        raise AppError("FORBIDDEN", "需要授权操作员与对账原因。", 403)
    locked_policy()
    ledger = UsageLedger.objects.select_for_update().get(job=job)
    if job.billing_mode != "platform_trial" or ledger.status != "unknown" or amount < 0:
        raise AppError("RECONCILIATION_INVALID", "只能核对平台未决费用。", 400)
    for window in (
        BudgetWindow.objects.select_for_update()
        .filter(pk__in=ledger.budget_window_ids)
        .order_by("id")
    ):
        window.reserved -= ledger.reserved_micros
        window.settled += amount
        window.save(update_fields=["reserved", "settled"])
    ledger.status, ledger.settled_micros = "settled", amount
    ledger.save(update_fields=["status", "settled_micros"])
    audit(actor, "platform_cost_reconciled", job, reason=reason.strip())
    # A separate audited policy edit is required to resume the circuit.
