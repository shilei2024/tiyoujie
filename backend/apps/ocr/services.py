import hashlib
import json
import re
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.models import Family, GuardianConsent
from apps.accounts.services import audit
from apps.credentials.models import UserProviderCredential
from apps.credentials.services import credential_for, decrypt
from apps.metering.models import BudgetWindow, PriceVersion, QuotaWindow
from apps.metering.services import finish, locked_policy, periods, reserve
from apps.problems.models import Problem, ProblemAsset
from apps.problems.services import append_text, asset_for, check_revision, problem_for
from apps.problems.storage import storage
from config.errors import AppError

from .models import OCRJob, OCRModel, Outbox
from .providers import TEMPLATE_ID, ProviderFailure, call_provider


def available_model(identifier, task_type="ocr"):
    model = get_object_or_404(OCRModel, pk=identifier)
    capable = (
        model.supports_vision
        if task_type == "ocr"
        else (model.supports_text and model.supports_json and model.analysis_enabled)
    )
    if not model.enabled or not capable or not model.runtime_approved:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "该模型尚未获准执行所选任务。", 409)
    if not model.notice.strip() or not model.notice_version.strip():
        raise AppError("PROVIDER_NOTICE_MISSING", "第三方处理说明尚未配置。", 503)
    return model


def consent(child_id, scope, identifier=None):
    query = GuardianConsent.objects.select_for_update().filter(
        child_id=child_id, scope=scope, revoked_at__isnull=True
    )
    if scope == "profile":
        query = query.filter(notice_version=settings.GUARDIAN_NOTICE_VERSION)
    if identifier:
        query = query.filter(pk=identifier)
    item = query.first()
    if not item:
        raise AppError("CONSENT_REQUIRED", "监护授权缺失或已撤回，请重新确认。", 403)
    return item


def platform_key(provider):
    key = settings.PLATFORM_OCR_KEYS.get(provider, "")
    if not key or "\n" in key or "\r" in key:
        raise AppError("PLATFORM_NOT_CONFIGURED", "平台 OCR 凭证尚未配置。", 503)
    return key


@transaction.atomic
def create_job(user, problem_id, data, idempotency_key, *, task_type="ocr"):
    if task_type not in {"ocr", "analysis"}:
        raise AppError("TASK_TYPE_INVALID", "任务类型不支持。", 400)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", idempotency_key):
        raise AppError("IDEMPOTENCY_REQUIRED", "请提供有效的请求幂等标识。", 400)
    problem = problem_for(user, problem_id, manage=True)
    payload = {
        "task_type": task_type,
        "problem_id": str(problem_id),
        **{key: str(value) for key, value in data.items()},
    }
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    policy = locked_policy()
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    existing = OCRJob.objects.filter(actor_id=user.pk, idempotency_key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise AppError("IDEMPOTENCY_CONFLICT", "同一请求标识不能用于不同内容。", 409)
        return existing
    problem = get_object_or_404(
        Problem.objects.select_for_update(), pk=problem.pk, deleted_at__isnull=True
    )
    check_revision(problem, data["expected_revision"])
    model = available_model(data["model_id"], task_type)
    asset, version, extra_snapshot = None, None, {}
    if task_type == "ocr":
        asset = asset_for(user, data["asset_id"], manage=True)
        get_object_or_404(ProblemAsset, problem=problem, asset=asset)
        if asset.object.byte_size > model.max_input_bytes:
            raise AppError("MODEL_INPUT_LIMIT", "图片超出该模型的输入限制，请裁剪后重试。", 400)
        input_sha = asset.sha256
    else:
        from apps.ai_tutor.providers import snapshot_fields
        from apps.ai_tutor.services import confirmed_version, input_hash, payload_for

        version = confirmed_version(problem, data["text_version_id"])
        input_sha = input_hash(payload_for(version, data["student_answer"], problem.child.grade))
        extra_snapshot = snapshot_fields(data["student_answer"])
    profile = consent(problem.child_id, "profile")
    provider_consent = consent(problem.child_id, model.provider)
    if data["notice_version"] != model.notice_version:
        raise AppError("NOTICE_CHANGED", "第三方处理说明已更新，请重新阅读确认。", 409)
    enabled = settings.OCR_OUTBOUND_ENABLED if task_type == "ocr" else settings.AI_ANALYSIS_ENABLED
    if not enabled:
        raise AppError(
            "OCR_DISABLED" if task_type == "ocr" else "AI_DISABLED",
            "外发尚未开放，可以先手动管理错题。",
            503,
        )
    now = timezone.now()
    if (
        OCRJob.objects.filter(
            family_id=problem.child.family_id, status__in=["queued", "running"]
        ).count()
        >= policy.family_pending_limit
    ):
        raise AppError("TASK_LIMIT", "家庭待处理任务过多，请稍后再试。", 429)
    mode = data["billing_mode"]
    credential = None
    if mode == "platform_trial":
        if data.get("credential_id"):
            raise AppError("MODE_BINDING_INVALID", "平台体验不能绑定个人凭证。", 400)
        if not settings.PLATFORM_AI_ENABLED or not policy.platform_enabled or policy.halted:
            raise AppError("PLATFORM_DISABLED", "平台体验当前不可用，请稍后再试。", 503)
        if model.provider not in settings.PLATFORM_OCR_CONFIGURED_PROVIDERS:
            raise AppError("PLATFORM_NOT_CONFIGURED", "平台 OCR 凭证尚未配置。", 503)
    else:
        if not data.get("credential_id"):
            raise AppError("CREDENTIAL_REQUIRED", "请选择自己的服务凭证。", 400)
        credential = credential_for(user, data["credential_id"])
        if (
            credential.family_id != problem.child.family_id
            or credential.provider != model.provider
            or not credential.enabled
        ):
            raise AppError("CREDENTIAL_REVOKED", "凭证不适用于本次识别。", 409)
        day, _, _ = periods(policy, now)
        if (
            OCRJob.objects.filter(
                family_id=problem.child.family_id,
                billing_mode="byok",
                created_at__gte=timezone.datetime.fromisoformat(day).replace(
                    tzinfo=ZoneInfo(policy.timezone_name)
                ),
            ).count()
            >= policy.byok_daily_limit
        ):
            raise AppError("TASK_LIMIT", "自有 API 今日任务次数已达上限。", 429)
    price = (
        PriceVersion.objects.filter(
            model=model, bound_reviewed=True, valid_from__lte=now, valid_until__gt=now
        )
        .order_by("-created_at")
        .first()
    )
    if mode == "platform_trial" and (not price or price.currency != policy.currency):
        raise AppError("PRICE_NOT_CONFIGURED", "平台计费上界尚未核定。", 503)
    price_data = (
        {
            key: getattr(price, key)
            for key in ("currency", "input_per_million", "output_per_million", "input_token_bound")
        }
        if price
        else {}
    )
    job = OCRJob.objects.create(
        actor_id=user.pk,
        family_id=problem.child.family_id,
        child_id=problem.child_id,
        problem=problem,
        task_type=task_type,
        asset=asset,
        text_version=version,
        model=model,
        price=price,
        billing_mode=mode,
        credential_id=credential.pk if credential else None,
        credential_version=credential.credential_version if credential else None,
        profile_consent_id=profile.pk,
        provider_consent_id=provider_consent.pk,
        input_revision=problem.revision,
        input_sha256=input_sha,
        snapshot={
            "provider": model.provider,
            "model_name": model.model_name,
            "max_output_tokens": model.max_output_tokens,
            "notice_version": model.notice_version,
            "template_id": TEMPLATE_ID,
            "quota_units": model.ocr_quota_units
            if task_type == "ocr"
            else model.analysis_quota_units,
            **extra_snapshot,
        },
        price_snapshot=price_data,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if task_type == "analysis":
        from apps.ai_tutor.models import AnalysisInput

        AnalysisInput.objects.create(
            problem=problem,
            job=job,
            student_answer=data["student_answer"],
            grade=problem.child.grade,
        )
    reserve(job, policy, now)
    Outbox.objects.create(job=job)
    audit(
        user, "ocr_queued" if task_type == "ocr" else "analysis_queued", job, problem.child.family
    )
    transaction.on_commit(publish_outbox, robust=True)
    return job


def publish_outbox():
    from .tasks import execute_ocr

    now = timezone.now()
    for outbox in Outbox.objects.filter(job__status="queued"):
        if outbox.last_published_at and outbox.last_published_at > now - timedelta(seconds=30):
            continue
        execute_ocr.apply_async(args=[str(outbox.job_id)])
        Outbox.objects.filter(pk=outbox.pk).update(last_published_at=now)


def job_for(user, identifier, manage=False):
    job = get_object_or_404(OCRJob, pk=identifier, problem__isnull=False)
    problem = problem_for(user, job.problem_id, manage=manage)
    if manage and user.pk != job.actor_id and user.pk != problem.child.family.owner_id:
        raise AppError("FORBIDDEN", "没有该任务的操作权限。", 403)
    return job


def budget_still_valid(job, policy, now):
    if not settings.PLATFORM_AI_ENABLED or not policy.platform_enabled or policy.halted:
        return False
    if (
        not job.reservation_until
        or now >= job.reservation_until
        or not job.price
        or not job.price.valid_from <= now < job.price.valid_until
    ):
        return False
    day, month, _ = periods(policy, now)
    limits = {
        "lifetime": policy.lifetime_limit,
        "month": policy.month_limit,
        "day": policy.day_limit,
        "family_day": policy.family_day_limit,
    }
    ledger = job.usageledger
    units = job.snapshot.get("quota_units", 1)
    if type(units) is not int or not 1 <= units <= 20:
        return False
    windows = list(BudgetWindow.objects.filter(pk__in=ledger.budget_window_ids))
    quotas = list(QuotaWindow.objects.filter(pk__in=ledger.quota_window_ids))
    if ledger.status != "reserved" or len(windows) != 4 or len(quotas) != 3:
        return False
    for quota in quotas:
        quota_limit = (
            policy.family_total_quota
            if quota.period == "lifetime"
            else policy.user_daily_quota
            if quota.scope.startswith("user:")
            else policy.family_daily_quota
        )
        if quota.reserved < units or quota.reserved + quota.consumed > quota_limit:
            return False
    for window in windows:
        if window.reserved < ledger.reserved_micros:
            return False
        if window.settled + window.reserved > limits[window.kind]:
            return False
        if window.kind == "month" and window.period != month:
            return False
        if window.kind in {"day", "family_day"} and window.period != day:
            return False
    return True


@transaction.atomic
def prepare(identifier):
    policy = locked_policy()
    job = (
        OCRJob.objects.select_for_update(of=("self",))
        .select_related("model", "price")
        .filter(pk=identifier)
        .first()
    )
    if not job or job.status != "queued":
        return None
    now = timezone.now()
    try:
        user = get_user_model().objects.filter(pk=job.actor_id, is_active=True).first()
        if not user or not job.problem_id or job.cancel_requested:
            raise AppError("TASK_CANCELLED", "任务已取消。", 409)
        Family.objects.select_for_update().get(pk=job.family_id)
        problem = problem_for(user, job.problem_id, manage=True)
        model = available_model(job.model_id, job.task_type)
        if (
            any(
                getattr(model, name) != job.snapshot[name]
                for name in ("provider", "model_name", "notice_version")
            )
            or model.max_output_tokens < job.snapshot["max_output_tokens"]
        ):
            raise AppError("MODEL_CHANGED", "模型配置已变更。", 409)
        if job.task_type == "ocr":
            asset = asset_for(user, job.asset_id, manage=True)
            get_object_or_404(ProblemAsset, problem_id=job.problem_id, asset=asset)
            if asset.sha256 != job.input_sha256 or asset.object.byte_size > model.max_input_bytes:
                raise AppError("INPUT_CHANGED", "输入图片已变更。", 409)
            image = storage().read(asset.object.object_key)
            if hashlib.sha256(image).hexdigest() != job.input_sha256:
                raise AppError("INPUT_CHANGED", "输入文件校验失败。", 409)
        else:
            from apps.ai_tutor.services import prepare_payload

            image = prepare_payload(job, problem)
        consent(job.child_id, "profile", job.profile_consent_id)
        consent(job.child_id, model.provider, job.provider_consent_id)
        enabled = (
            settings.OCR_OUTBOUND_ENABLED
            if job.task_type == "ocr"
            else settings.AI_ANALYSIS_ENABLED
        )
        if not enabled:
            raise AppError(
                "OCR_DISABLED" if job.task_type == "ocr" else "AI_DISABLED", "外发已关闭。", 503
            )
        if job.billing_mode == "platform_trial":
            if not budget_still_valid(job, policy, now):
                raise AppError("BUDGET_RECHECK_FAILED", "预算或价格需要重新检查。", 409)
            key = platform_key(model.provider)
        else:
            credential_for(user, job.credential_id)
            credential = get_object_or_404(
                UserProviderCredential.objects.select_for_update(),
                pk=job.credential_id,
                enabled=True,
                deleted_at__isnull=True,
                credential_version=job.credential_version,
                family_id=job.family_id,
                provider=model.provider,
            )
            key = decrypt(credential)
        if not 8 <= len(key) <= 512 or not key.isascii() or any(ch.isspace() for ch in key):
            raise AppError("CREDENTIAL_INVALID", "服务凭证格式不可用，请重新配置。", 409)
    except (AppError, Http404, ObjectDoesNotExist, OSError) as error:
        job.status, job.error_code, job.completed_at = (
            "failed",
            getattr(error, "public_code", "TASK_ACCESS_REVOKED"),
            now,
        )
        job.save(update_fields=["status", "error_code", "completed_at"])
        finish(job, definitely_unsent=True)
        return None
    job.status, job.sent_at = "running", now
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = now + timedelta(seconds=75)
    job.save(update_fields=["status", "sent_at", "lease_token", "lease_expires_at"])
    snapshot = {
        **job.snapshot,
        "send_before": job.reservation_until.isoformat() if job.reservation_until else None,
    }
    return job.pk, job.lease_token, snapshot, image, key


@transaction.atomic
def complete(identifier, lease_token, outcome=None, error_code="", definitely_unsent=False):
    locked_policy()
    job = (
        OCRJob.objects.select_for_update()
        .filter(pk=identifier, status="running", lease_token=lease_token)
        .first()
    )
    if not job:
        return
    candidate = outcome.candidate if outcome else None
    allowed = False
    if candidate and not job.cancel_requested and job.problem_id:
        try:
            user = get_user_model().objects.get(pk=job.actor_id, is_active=True)
            problem = problem_for(user, job.problem_id, manage=True)
            consent(job.child_id, "profile", job.profile_consent_id)
            consent(job.child_id, job.snapshot["provider"], job.provider_consent_id)
            problem = Problem.objects.select_for_update().get(pk=problem.pk)
            if job.task_type == "analysis":
                from apps.ai_tutor.services import store_result

                store_result(job, problem, candidate)
            else:
                append_text(
                    problem,
                    origin="ocr",
                    text=candidate["text"],
                    confirmed=False,
                    ocr_job_id=job.pk,
                    confidence=candidate["confidence"],
                    uncertainties=candidate["uncertainties"],
                )
            # Never overwrite current_text, even if the user edited while OCR was in flight.
            allowed = True
        except (AppError, Http404, ObjectDoesNotExist):
            error_code = "TASK_ACCESS_REVOKED"
        except ValueError:
            error_code = "AI_OUTPUT_INVALID"
    success = bool(candidate and allowed)
    finish(
        job,
        success=success,
        usage=outcome.usage if outcome else None,
        definitely_unsent=definitely_unsent,
    )
    if job.billing_mode == "byok" and not definitely_unsent:
        connection_status = {
            "PROVIDER_AUTH_INVALID": "auth_failed",
            "PROVIDER_BALANCE_INSUFFICIENT": "insufficient_balance",
            "PROVIDER_PERMISSION_DENIED": "permission_denied",
            "PROVIDER_RATE_LIMITED": "rate_limited",
        }.get(error_code, "response_received" if outcome is not None else "outcome_unknown")
        UserProviderCredential.objects.filter(
            pk=job.credential_id,
            owner_id=job.actor_id,
            family_id=job.family_id,
            provider=job.snapshot["provider"],
            credential_version=job.credential_version,
            enabled=True,
            deleted_at__isnull=True,
        ).update(validation_status=connection_status, updated_at=timezone.now())
    job.status = (
        ("completed" if job.task_type == "analysis" else "needs_review")
        if success
        else "cancelled"
        if job.cancel_requested
        else "failed"
    )
    job.error_code = error_code or (outcome.error_code if outcome else "PROVIDER_UNAVAILABLE")
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_code", "completed_at"])


def run_job(identifier):
    prepared = prepare(identifier)
    if not prepared:
        return
    pk, lease, snapshot, image, key = prepared
    try:
        outcome = call_provider(snapshot, image, key)
    except Exception as error:
        complete(
            pk,
            lease,
            error_code=error.code if isinstance(error, ProviderFailure) else "PROVIDER_UNAVAILABLE",
            definitely_unsent=isinstance(error, ProviderFailure) and error.definitely_unsent,
        )
    else:
        complete(pk, lease, outcome=outcome)


@transaction.atomic
def cancel_scope(**filters):
    locked_policy(required=False)
    for job in (
        OCRJob.objects.select_for_update()
        .filter(status__in=["queued", "running"], **filters)
        .order_by("id")
    ):
        job.cancel_requested = True
        if job.status == "queued":
            finish(job, definitely_unsent=True)
            job.status, job.completed_at = "cancelled", timezone.now()
        job.save(update_fields=["cancel_requested", "status", "completed_at"])


def recover_jobs(now=None):
    now = now or timezone.now()
    for identifier in OCRJob.objects.filter(status="running", lease_expires_at__lt=now).values_list(
        "id", flat=True
    ):
        with transaction.atomic():
            locked_policy()
            job = OCRJob.objects.select_for_update().get(pk=identifier)
            if job.status != "running" or job.lease_expires_at >= now:
                continue
            finish(job)
            job.status, job.error_code, job.completed_at = "failed", "PROVIDER_OUTCOME_UNKNOWN", now
            job.save(update_fields=["status", "error_code", "completed_at"])
    publish_outbox()
