import json
import re

from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.models import Family
from apps.accounts.services import audit
from apps.problems.services import problem_for, require_profile_consent
from config.errors import AppError

from .math_verifier import number, verify
from .models import (
    KnowledgePoint,
    QuestionBankItem,
    QuestionSource,
    VariantDraft,
    VerificationRecord,
    digest,
    fingerprint,
)
from .serializers import ImportInput


def staff(user, permission):
    if not user.is_active or not user.is_staff or not user.has_perm(f"question_bank.{permission}"):
        raise AppError("FORBIDDEN", "需要指定的题库管理权限。", 403)


def source_usable(source):
    now = timezone.now()
    return (
        source.review_status == "approved"
        and source.allow_public
        and source.source_type not in {"unknown", "user_upload"}
        and source.valid_from <= now < source.valid_until
        and source.reviewed_by_id is not None
        and source.reviewed_at is not None
        and source.reviewed_digest == source.content_digest()
    )


@transaction.atomic
def review_source(user, source_id, decision, reason):
    staff(user, "review_bank")
    source = get_object_or_404(QuestionSource.objects.select_for_update(), pk=source_id)
    if decision not in {"approved", "rejected"} or not reason.strip():
        raise AppError("REVIEW_REQUIRED", "请填写审核决定与依据。")
    if decision == "approved" and (
        not all(
            getattr(source, name).strip()
            for name in [
                "source_reference",
                "license_name",
                "rights_evidence",
                "attribution",
                "usage_conditions",
            ]
        )
        or source.source_type in {"unknown", "user_upload"}
        or not source.allow_public
        or not source.valid_from <= timezone.now() < source.valid_until
    ):
        raise AppError("RIGHTS_INCOMPLETE", "授权、公开使用范围或有效期未满足审核条件。")
    source.review_status, source.review_reason = decision, reason[:500]
    source.reviewed_digest = source.content_digest()
    source.reviewed_by, source.reviewed_at = user, timezone.now()
    source.save()
    audit(user, "bank_source_reviewed", source, reason=decision + ": " + reason[:300])
    return source


def validate_import(user, raw):
    staff(user, "add_questionbankitem")
    if len(json.dumps(raw, ensure_ascii=False)) > 48000:
        raise AppError("IMPORT_TOO_LARGE", "每次最多 20 题、48,000 字符，请分批导入。")
    serializer = ImportInput(data=raw)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    source = get_object_or_404(QuestionSource, pk=data["source_id"])
    seen, rows = {}, []
    for index, item in enumerate(data["items"], 1):
        key = fingerprint(item["text"])
        old = QuestionBankItem.objects.filter(fingerprint=key).first()
        duplicate = key in seen or old is not None
        rows.append(
            {
                "row": index,
                "text": item["text"],
                "duplicate": duplicate,
                "answer_conflict": bool(old and old.answer != item["answer"])
                or (key in seen and seen[key] != item["answer"]),
                "math_check": verify(item["math_spec"], item["answer"]).payload(),
            }
        )
        seen[key] = item["answer"]
    binding = {
        "actor": user.pk,
        "source": str(source.pk),
        "revision": source.revision,
        "digest": digest(raw),
    }
    return data, source, rows, binding


def preview_import(user, raw):
    _, source, rows, binding = validate_import(user, raw)
    return {
        "rows": rows,
        "source_review_status": source.review_status,
        "public_eligible": source_usable(source),
        "preview_token": signing.dumps(binding, salt="bank-import-v1", compress=True),
    }


@transaction.atomic
def commit_import(user, raw, token):
    data, source, rows, binding = validate_import(user, raw)
    try:
        signed = signing.loads(token, salt="bank-import-v1", max_age=600)
    except signing.BadSignature:
        raise AppError("PREVIEW_EXPIRED", "预览已失效，请重新预览。", 409) from None
    if signed != binding:
        raise AppError("PREVIEW_CHANGED", "内容或来源已改变，请重新预览。", 409)
    source = QuestionSource.objects.select_for_update().get(pk=source.pk)
    if source.revision != binding["revision"]:
        raise AppError("PREVIEW_CHANGED", "来源已改变，请重新预览。", 409)
    created, created_ids = 0, []
    for item in data["items"]:
        try:
            with transaction.atomic():
                question = QuestionBankItem.objects.create(source=source, **item)
                created += 1
                created_ids.append(str(question.pk))
        except IntegrityError:
            if not QuestionBankItem.objects.filter(fingerprint=fingerprint(item["text"])).exists():
                raise
    audit(
        user, "bank_imported", source, reason=f"created={created};duplicates={len(rows) - created}"
    )
    return {
        "created": created,
        "created_ids": created_ids,
        "duplicates": len(rows) - created,
        "review_status": "pending",
    }


@transaction.atomic
def check_item(user, item_id):
    staff(user, "review_bank")
    item = get_object_or_404(QuestionBankItem.objects.select_for_update(), pk=item_id)
    result = verify(item.math_spec, item.answer)
    VerificationRecord.objects.create(
        item=item,
        revision=item.revision,
        content_hash=item.content_hash,
        result={**result.payload(), "input_snapshot": item.content_data()},
        actor=user,
    )
    # A machine check never grants publication and invalidates an earlier human decision.
    item.review_status, item.reviewed_hash = "pending", ""
    item.reviewed_by, item.reviewed_at, item.reviewed_source_revision = None, None, None
    item.verification_status = (
        "machine_checked"
        if result.result == "correct"
        else "rejected"
        if result.result == "incorrect"
        else "imported_unverified"
    )
    item.verification_method = result.method
    item.verified_by, item.verified_at = user, timezone.now()
    item.save()
    audit(user, "bank_math_checked", item, reason=result.result)
    return result.payload()


@transaction.atomic
def review_item(
    user,
    item_id,
    decision,
    reason,
    *,
    statement_checked=False,
    answer_checked=False,
    explanation_checked=False,
):
    staff(user, "review_bank")
    initial = get_object_or_404(QuestionBankItem, pk=item_id)
    source = QuestionSource.objects.select_for_update().get(pk=initial.source_id)
    item = QuestionBankItem.objects.select_for_update().get(pk=item_id)
    if item.source_id != source.pk:
        raise AppError("REVIEW_CHANGED", "题目来源已改变，请重新审核。", 409)
    if decision not in {"approved", "rejected"} or not reason.strip():
        raise AppError("REVIEW_REQUIRED", "请填写审核决定与依据。")
    if decision == "approved":
        if not source_usable(source):
            raise AppError("RIGHTS_NOT_APPROVED", "来源授权未审核通过或已到期。")
        if not statement_checked or not explanation_checked:
            raise AppError("HUMAN_REVIEW_REQUIRED", "请人工核对题干、建模对应关系与解析。")
        latest = (
            item.checks.filter(content_hash=item.content_hash, revision=item.revision)
            .order_by("-created_at")
            .first()
        )
        if latest and latest.result["result"] in {"incorrect", "invalid"}:
            raise AppError("MATH_CHECK_FAILED", "当前答案核验失败，请更正后重新审核。")
        if not answer_checked and not (latest and latest.result["result"] == "correct"):
            raise AppError("HUMAN_REVIEW_REQUIRED", "此题未获机器核验支持，请人工核验答案。")
        item.verification_status = "human_verified" if answer_checked else "machine_checked"
        item.verification_method = "human_review" if answer_checked else latest.result["method"]
        item.verified_by, item.verified_at = user, timezone.now()
        if answer_checked:
            VerificationRecord.objects.create(
                item=item,
                revision=item.revision,
                content_hash=item.content_hash,
                result={
                    "result": "human_verified",
                    "method": "human_review",
                    "scope": "人工复核题干、答案、建模与解析",
                    "input_snapshot": item.content_data(),
                },
                actor=user,
            )
    else:
        item.verification_status = "rejected"
    item.review_status, item.review_reason = decision, reason[:500]
    item.reviewed_hash, item.reviewed_source_revision = item.content_hash, source.revision
    item.reviewed_by, item.reviewed_at = user, timezone.now()
    item.save()
    audit(user, "bank_item_reviewed", item, reason=decision + ": " + reason[:300])
    return item


def trusted_items():
    now = timezone.now()
    return (
        QuestionBankItem.objects.select_related("source")
        .filter(
            review_status="approved",
            reviewed_hash=F("content_hash"),
            reviewed_source_revision=F("source__revision"),
            verification_status__in=["machine_checked", "human_verified"],
            reviewed_by__isnull=False,
            source__review_status="approved",
            source__allow_public=True,
            source__valid_from__lte=now,
            source__valid_until__gt=now,
        )
        .exclude(source__source_type__in=["unknown", "user_upload"])
    )


def similar(user, problem_id, filters):
    problem = problem_for(user, problem_id)
    if not problem.current_text_id:
        raise AppError("CONFIRMED_TEXT_REQUIRED", "请先确认题干。")
    query = trusted_items()
    for field in ("grade", "difficulty", "question_type", "solution_structure"):
        if filters.get(field) is not None:
            query = query.filter(**{field: filters[field]})
    points = set(problem.knowledge_points)
    codes = set(
        KnowledgePoint.objects.filter(
            Q(code__in=points) | Q(name__in=points), enabled=True
        ).values_list("code", flat=True)
    )
    if filters.get("knowledge_point"):
        codes = {filters["knowledge_point"]}
        query = query.filter(knowledge_points__contains=[filters["knowledge_point"]])
    keyword = filters.get("q", "").strip()
    relevance = Q(pk__isnull=True)
    for code in codes:
        relevance |= Q(knowledge_points__contains=[code])
    if keyword:
        relevance |= Q(text__icontains=keyword)
    if not codes and not keyword:
        return {
            "results": [],
            "candidate_limit": 200,
            "truncated": False,
            "reason": "请补充知识点或输入检索词。",
        }
    candidates = list(query.filter(relevance).order_by("-reviewed_at", "id")[:201])
    ranked = []
    for item in candidates[:200]:
        if not source_usable(item.source) or item.content_hash != item.content_digest():
            continue
        shared = sorted(codes.intersection(item.knowledge_points))
        score, reasons = 4 * len(shared), []
        if shared:
            reasons.append("知识点相同：" + "、".join(shared))
        if keyword and keyword.casefold() in item.text.casefold():
            score += 2
            reasons.append("题干包含检索词")
        for field, label in (
            ("question_type", "题型"),
            ("solution_structure", "解题结构"),
            ("difficulty", "难度"),
            ("grade", "年级"),
        ):
            if filters.get(field) is not None:
                score += 1
                reasons.append(label + "符合筛选条件")
        ranked.append((score, str(item.pk), item, reasons))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return {
        "results": [(item, reasons) for _, _, item, reasons in ranked[:20]],
        "candidate_limit": 200,
        "truncated": len(candidates) > 200,
        "reason": "按知识点和关键词检索；可用题型、解题结构、难度与年级缩小范围。",
    }


def variant_payload(item, intent):
    spec = item.math_spec
    if spec.get("kind") != "arithmetic" or verify(spec, item.answer).result != "correct":
        raise AppError("VARIANT_NOT_SUPPORTED", "规则变式目前仅支持已核验的有理数四则运算题。")
    expression, target = spec["expression"], number(item.answer)
    if len(expression) > 100:
        raise AppError("VARIANT_NOT_SUPPORTED", "此算式较长，请人工设计变式。")
    if intent == "numbers":
        new_spec, answer = (
            {"kind": "arithmetic", "expression": f"({expression})+1"},
            str(target + 1),
        )
        text = "计算：" + new_spec["expression"]
    elif intent == "conditions":
        new_spec, answer = (
            {"kind": "arithmetic", "expression": f"({expression})/2"},
            str(target / 2),
        )
        text = "求下列算式结果的一半：" + expression
    elif intent == "reverse":
        new_spec, answer = (
            {"kind": "linear_equation", "left": f"x+({expression})", "right": str(target + 1)},
            "1",
        )
        text = f"求 x：{new_spec['left']} = {new_spec['right']}"
    elif intent == "context":
        if not 0 < target <= 10000:
            raise AppError(
                "VARIANT_NOT_SUPPORTED", "情境变式目前仅支持结果为正且不超过 10000 的算式。"
            )
        new_spec, answer = (
            {"kind": "arithmetic", "expression": f"2*({expression})"},
            str(target * 2),
        )
        text = f"每份材料长 ({expression}) 米，两份合计多少米？"
    else:
        raise AppError("INVALID_INTENT", "请选择支持的变式方向。")
    return {
        "text": text,
        "answer": answer,
        "explanation": "规则改写候选，请人工核对题意、单位与解题过程。",
        "options": [],
        "knowledge_points": item.knowledge_points,
        "difficulty": item.difficulty,
        "math_spec": new_spec,
        "machine_check": verify(new_spec, answer).payload(),
    }


@transaction.atomic
def create_variant(user, problem_id, data, key):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        raise AppError("IDEMPOTENCY_REQUIRED", "请使用有效的请求标识。")
    initial = problem_for(user, problem_id, manage=True)
    Family.objects.select_for_update().get(pk=initial.child.family_id)
    problem = problem_for(user, problem_id, manage=True)
    require_profile_consent(problem.child)
    request_hash = digest({k: str(v) for k, v in data.items()})
    previous = VariantDraft.objects.filter(problem=problem, request_key=key).first()
    if previous:
        if previous.request_hash != request_hash:
            raise AppError("IDEMPOTENCY_CONFLICT", "同一请求标识对应了不同内容。", 409)
        return previous
    if (
        problem.current_text_id != data["text_version_id"]
        or problem.revision != data["expected_revision"]
    ):
        raise AppError("REVISION_CONFLICT", "题干已更改，请重新载入。", 409)
    if VariantDraft.objects.filter(problem=problem).count() >= 50:
        raise AppError("DRAFT_LIMIT", "每道错题最多保留 50 份变式草稿。", 409)
    initial_item = get_object_or_404(trusted_items(), pk=data["bank_item_id"])
    source = QuestionSource.objects.select_for_update().get(pk=initial_item.source_id)
    item = get_object_or_404(
        trusted_items().select_for_update(of=("self",)), pk=data["bank_item_id"]
    )
    if item.source_id != source.pk:
        raise AppError("REVIEW_CHANGED", "题目来源已改变，请重试。", 409)
    item.source = source
    if not source_usable(item.source):
        raise AppError("RIGHTS_NOT_APPROVED", "题目授权已不可用。", 409)
    draft = VariantDraft.objects.create(
        problem=problem,
        text_version=problem.current_text,
        bank_item_id=item.pk,
        bank_revision=item.revision,
        intent=data["intent"],
        payload=variant_payload(item, data["intent"]),
        generator="deterministic-variants-v1",
        created_by=user,
        request_key=key,
        request_hash=request_hash,
    )
    audit(user, "variant_draft_created", draft, problem.child.family)
    return draft
