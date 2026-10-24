import hashlib
import json

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404

from apps.accounts.models import Family
from apps.accounts.services import audit
from apps.problems.models import ProblemTextVersion
from apps.problems.services import problem_for, require_profile_consent
from config.errors import AppError

from .models import Analysis, AnalysisFeedback, AnalysisInput
from .schema import safe_text, validate


def payload_for(version, student_answer, grade):
    return {
        "text_version_id": str(version.pk),
        "confirmed_text": version.text,
        "student_answer": student_answer,
        "grade": grade,
        "images_included": False,
    }


def input_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def confirmed_version(problem, identifier):
    version = get_object_or_404(ProblemTextVersion, pk=identifier, problem=problem, confirmed=True)
    if problem.current_text_id != version.pk:
        raise AppError("INPUT_CHANGED", "请先载入当前已确认的题干版本。", 409)
    if not version.text.strip() or len(version.text) > 20000:
        raise AppError("INPUT_INVALID", "题干长度不符合分析要求。", 400)
    return version


def prepare_payload(job, problem):
    item = get_object_or_404(AnalysisInput, job=job, problem=problem)
    version = confirmed_version(problem, job.text_version_id)
    if len(item.student_answer) > 4000:
        raise AppError("INPUT_INVALID", "作答内容过长。", 400)
    payload = payload_for(version, item.student_answer, item.grade)
    if (
        input_hash(payload) != job.input_sha256
        or bool(item.student_answer.strip()) != job.snapshot["has_student_work"]
    ):
        raise AppError("INPUT_CHANGED", "本次分析输入已变化。", 409)
    return payload


def store_result(job, problem, candidate):
    get_object_or_404(AnalysisInput, job=job, problem=problem)
    get_object_or_404(ProblemTextVersion, pk=job.text_version_id, problem=problem, confirmed=True)
    validate(candidate, has_student_work=job.snapshot["has_student_work"])
    Analysis.objects.create(problem=problem, job=job, payload=candidate)


@transaction.atomic
def add_feedback(user, identifier, data):
    item = get_object_or_404(Analysis, pk=identifier)
    problem = problem_for(user, item.problem_id, manage=True)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    require_profile_consent(problem.child)
    item = Analysis.objects.select_for_update().get(pk=item.pk)
    try:
        safe_text(data["text"], 4000)
    except ValueError:
        raise AppError("FEEDBACK_INVALID", "请使用纯文本提交修订或问题说明。", 400) from None
    number = (item.feedback.aggregate(last=Max("number"))["last"] or 0) + 1
    result = AnalysisFeedback.objects.create(analysis=item, number=number, created_by=user, **data)
    audit(user, "analysis_feedback_added", result, problem.child.family)
    return result
