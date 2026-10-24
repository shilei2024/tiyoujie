import csv
import html
import io
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.access import child_for
from apps.accounts.models import Family
from apps.accounts.services import audit
from apps.problems.models import Problem
from apps.problems.services import problem_for, require_profile_consent
from apps.question_bank.math_verifier import verify
from apps.question_bank.models import VariantDraft
from apps.question_bank.services import source_usable, trusted_items
from config.errors import AppError

from .models import Attempt, ExportTicket, ReviewEvent, ReviewSchedule, Worksheet, WorksheetItem

# Deterministic ladder; no machine learning, no provider call.
INTERVALS = (1, 3, 7, 14, 30, 60, 120)
MAX_ITEMS = 30
MAX_WORKSHEETS = 200
MAX_ATTEMPTS = 20
EXPORT_MINUTES = 10
TREND_WEEKS = 8
MIN_SAMPLE = 10
MIN_POINT_SAMPLE = 5


def local_today():
    return timezone.now().astimezone(ZoneInfo(settings.PRACTICE_TIME_ZONE)).date()


def check_title(title):
    value = " ".join(title.split())
    if not value:
        raise AppError("TITLE_REQUIRED", "请填写题单名称。")
    return value[:40]


def worksheet_for(user, identifier, manage=False):
    worksheet = get_object_or_404(
        Worksheet.objects.select_related("child"),
        pk=identifier,
        deleted_at__isnull=True,
        child__deleted_at__isnull=True,
    )
    child_for(user, worksheet.child_id, manage=manage)
    return worksheet


def list_worksheets(user, child_id):
    child = child_for(user, child_id)
    return (
        Worksheet.objects.filter(child=child, deleted_at__isnull=True)
        .annotate(item_count=Count("items"))
        .order_by("-created_at", "-id")
    )


@transaction.atomic
def create_worksheet(user, data):
    child = child_for(user, data["child_id"], manage=True)
    Family.objects.select_for_update().get(pk=child.family_id)
    require_profile_consent(child)
    if Worksheet.objects.filter(child=child, deleted_at__isnull=True).count() >= MAX_WORKSHEETS:
        raise AppError("WORKSHEET_LIMIT", "该孩子的题单数量已达上限。", 403)
    worksheet = Worksheet.objects.create(
        child=child, title=check_title(data["title"]), created_by=user
    )
    audit(user, "worksheet_created", worksheet, child.family)
    return worksheet


@transaction.atomic
def delete_worksheet(user, identifier):
    worksheet = worksheet_for(user, identifier, manage=True)
    Family.objects.select_for_update().get(pk=worksheet.child.family_id)
    worksheet = Worksheet.objects.select_for_update().get(pk=worksheet.pk)
    worksheet.deleted_at, worksheet.revision = timezone.now(), worksheet.revision + 1
    worksheet.save(update_fields=["deleted_at", "revision"])
    ExportTicket.objects.filter(worksheet=worksheet, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    audit(user, "worksheet_deleted", worksheet, worksheet.child.family)
    return worksheet


def bank_snapshot(item):
    return {
        "origin": "bank",
        "bank_item_id": item.pk,
        "bank_revision": item.revision,
        "text": item.text,
        "answer": item.answer,
        "explanation": item.explanation,
        "knowledge_points": item.knowledge_points,
        "math_spec": item.math_spec,
    }


def problem_snapshot(problem):
    text = problem.current_text
    if not text or not text.confirmed:
        raise AppError("CONFIRMED_TEXT_REQUIRED", "请先确认题干后再加入题单。")
    return {
        "origin": "problem",
        "problem": problem,
        "text": text.text,
        "answer": text.answer,
        "explanation": "",
        "knowledge_points": problem.knowledge_points,
        "math_spec": {},
    }


@transaction.atomic
def add_item(user, identifier, data):
    worksheet = worksheet_for(user, identifier, manage=True)
    Family.objects.select_for_update().get(pk=worksheet.child.family_id)
    worksheet = Worksheet.objects.select_for_update().get(pk=worksheet.pk)
    require_profile_consent(worksheet.child)
    if worksheet.items.count() >= MAX_ITEMS:
        raise AppError("ITEM_LIMIT", f"每份题单最多 {MAX_ITEMS} 道题。", 409)
    if data["origin"] == "problem":
        problem = problem_for(user, data["problem_id"], manage=True)
        if problem.child_id != worksheet.child_id:
            raise AppError("SCOPE_MISMATCH", "只能加入同一孩子的错题。", 400)
        snapshot = problem_snapshot(problem)
        if worksheet.items.filter(problem=problem).exists():
            raise AppError("ITEM_DUPLICATE", "这道错题已在题单中。", 409)
    elif data["origin"] == "bank":
        item = get_object_or_404(trusted_items(), pk=data["bank_item_id"])
        if not source_usable(item.source):
            raise AppError("RIGHTS_NOT_APPROVED", "题目授权不可用。", 409)
        snapshot = bank_snapshot(item)
    else:
        draft = get_object_or_404(
            VariantDraft.objects.select_related("problem", "text_version"),
            pk=data["variant_id"],
            problem__child_id=worksheet.child_id,
            problem__deleted_at__isnull=True,
        )
        problem_for(user, draft.problem_id, manage=True)
        if draft.text_version_id != draft.problem.current_text_id:
            raise AppError("REVISION_CONFLICT", "变式草稿对应的是旧题干，请重新生成。", 409)
        payload = draft.payload or {}
        snapshot = {
            "origin": "variant",
            "problem": draft.problem,
            "text": payload.get("text", ""),
            "answer": payload.get("answer", ""),
            "explanation": payload.get("explanation", ""),
            "knowledge_points": payload.get("knowledge_points", []),
            "math_spec": payload.get("math_spec", {}),
        }
    if not snapshot["text"].strip():
        raise AppError("ITEM_EMPTY", "题目内容为空，无法加入题单。", 409)
    item = WorksheetItem.objects.create(
        worksheet=worksheet,
        position=worksheet.items.count() + 1,
        origin=snapshot["origin"],
        problem=snapshot.get("problem"),
        bank_item_id=snapshot.get("bank_item_id"),
        bank_revision=snapshot.get("bank_revision"),
        text=snapshot["text"],
        answer=snapshot["answer"] or "",
        explanation=snapshot["explanation"] or "",
        knowledge_points=snapshot["knowledge_points"] or [],
        math_spec=snapshot["math_spec"] or {},
    )
    worksheet.revision = worksheet.revision + 1
    worksheet.save(update_fields=["revision"])
    audit(user, "worksheet_item_added", item, worksheet.child.family)
    return item


@transaction.atomic
def remove_item(user, identifier, item_id):
    worksheet = worksheet_for(user, identifier, manage=True)
    Family.objects.select_for_update().get(pk=worksheet.child.family_id)
    item = get_object_or_404(
        WorksheetItem.objects.select_for_update(), pk=item_id, worksheet=worksheet
    )
    item.delete()
    for index, remaining in enumerate(worksheet.items.order_by("position"), 1):
        if remaining.position != index:
            remaining.position = index
            remaining.save(update_fields=["position"])
    worksheet.revision = worksheet.revision + 1
    worksheet.save(update_fields=["revision"])
    audit(user, "worksheet_item_removed", worksheet, worksheet.child.family)
    return worksheet


def item_source_available(item):
    if item.origin == "bank":
        return trusted_items().filter(pk=item.bank_item_id, revision=item.bank_revision).exists()
    if item.problem_id is None:
        return False
    return (
        Problem.objects.filter(pk=item.problem_id, deleted_at__isnull=True).exists()
        and item.worksheet.deleted_at is None
    )


def item_summary(item, reveal=False):
    available = item_source_available(item)
    attempts = list(item.attempts.order_by("number"))
    last = attempts[-1] if attempts else None
    data = {
        "id": str(item.pk),
        "position": item.position,
        "origin": item.origin,
        "knowledge_points": item.knowledge_points,
        "source_available": available,
        "attempts": len(attempts),
        "last_grade": last.self_grade if last else None,
        "last_correct": last.is_correct if last else None,
    }
    if available:
        data["text"] = item.text
    if reveal and available:
        data["answer"] = item.answer
        data["explanation"] = item.explanation
    return data


def worksheet_payload(worksheet, reveal):
    items = worksheet.items.select_related("problem", "worksheet").order_by("position")
    return {
        "id": str(worksheet.pk),
        "child_id": str(worksheet.child_id),
        "title": worksheet.title,
        "revision": worksheet.revision,
        "created_at": worksheet.created_at,
        "item_count": len(items),
        "items": [item_summary(item, reveal=reveal) for item in items],
    }


def auto_grade(item, answer):
    if not item.math_spec or not answer.strip():
        return None, "self"
    result = verify(item.math_spec, answer).result
    if result == "correct":
        return True, "auto"
    if result == "incorrect":
        return False, "auto"
    return None, "self"


def next_state(previous, grade, today):
    # level indexes INTERVALS; a first correct answer lands on the 1-day step.
    level = previous.level if previous else -1
    streak = previous.streak if previous else 0
    lapses = previous.lapses if previous else 0
    if grade == "correct":
        level = min(level + 1, len(INTERVALS) - 1)
        streak += 1
    elif grade == "unsure":
        level = max(level - 1, 0)
    else:
        level, streak, lapses = 0, 0, lapses + 1
    interval = INTERVALS[level]
    stage = (
        "mastered" if streak >= 4 and interval >= 30 else ("learning" if level <= 1 else "review")
    )
    return {
        "level": level,
        "interval_days": interval,
        "streak": streak,
        "lapses": lapses,
        "due_on": today + timedelta(days=interval),
        "stage": stage,
    }


@transaction.atomic
def apply_review(user, problem, grade):
    child = problem.child
    child_for(user, child.pk)
    Family.objects.select_for_update().get(pk=child.family_id)
    schedule = (
        ReviewSchedule.objects.select_for_update().filter(child=child, problem=problem).first()
    )
    today = local_today()
    state = next_state(schedule, grade, today)
    ReviewEvent.objects.create(
        child=child,
        problem=problem,
        grade=grade,
        level_before=schedule.level if schedule else 0,
        level_after=state["level"],
        interval_after=state["interval_days"],
        due_on=state["due_on"],
        actor=user,
    )
    if schedule is None:
        schedule = ReviewSchedule(child=child, problem=problem)
    for field in ("level", "interval_days", "streak", "lapses", "due_on", "stage"):
        setattr(schedule, field, state[field])
    schedule.last_graded_at = timezone.now()
    schedule.save()
    audit(user, "review_graded", problem, child.family, reason=grade)
    return schedule


@transaction.atomic
def submit_attempt(user, item_id, data):
    item = get_object_or_404(
        WorksheetItem.objects.select_related("worksheet", "problem"),
        pk=item_id,
        worksheet__deleted_at__isnull=True,
    )
    child_for(user, item.worksheet.child_id)
    Family.objects.select_for_update().get(pk=item.worksheet.child.family_id)
    item = WorksheetItem.objects.select_for_update().get(pk=item.pk)
    if not item_source_available(item):
        raise AppError("ITEM_UNAVAILABLE", "题目来源已变更或不可用。", 409)
    if item.attempts.count() >= MAX_ATTEMPTS:
        raise AppError("ATTEMPT_LIMIT", "这道题的可作答次数已达上限。", 409)
    is_correct, graded_by = auto_grade(item, data["answer"])
    if graded_by == "self":
        is_correct = {"correct": True, "wrong": False, "unsure": None}[data["self_grade"]]
    attempt = Attempt.objects.create(
        item=item,
        number=item.attempts.count() + 1,
        answer=data["answer"],
        self_grade=data["self_grade"],
        is_correct=is_correct,
        graded_by=graded_by,
        duration_seconds=data.get("duration_seconds"),
        actor=user,
    )
    schedule = None
    if item.problem_id is not None and item.origin != "bank":
        grade = "correct" if is_correct is True else "wrong" if is_correct is False else "unsure"
        schedule = apply_review(user, item.problem, grade)
        audit(user, "worksheet_attempt", item, item.worksheet.child.family, reason=grade)
    else:
        audit(user, "worksheet_attempt", item, item.worksheet.child.family)
    return attempt, schedule


def review_queue(user, child_id):
    child = child_for(user, child_id)
    today = local_today()
    schedules = (
        ReviewSchedule.objects.select_related("problem", "problem__current_text")
        .filter(child=child, problem__deleted_at__isnull=True)
        .order_by("due_on", "created_at")
    )
    due = [row for row in schedules if row.due_on <= today]
    fresh = (
        Problem.objects.filter(child=child, deleted_at__isnull=True)
        .exclude(pk__in=schedules.values("problem_id"))
        .order_by("-created_at")
    )
    rows = []
    for schedule in due[:20]:
        text = schedule.problem.current_text
        if text is None:
            continue
        rows.append(
            {
                "problem_id": str(schedule.problem_id),
                "text": text.text,
                "due_on": schedule.due_on,
                "overdue_days": (today - schedule.due_on).days,
                "stage": schedule.stage,
                "interval_days": schedule.interval_days,
                "streak": schedule.streak,
            }
        )
    for problem in fresh[: max(0, 20 - len(rows))]:
        if problem.current_text is None:
            continue
        rows.append(
            {
                "problem_id": str(problem.pk),
                "text": problem.current_text.text,
                "due_on": today,
                "overdue_days": 0,
                "stage": "new",
                "interval_days": 0,
                "streak": 0,
            }
        )
    counts = {
        "due": len(due),
        "new": fresh.count(),
        "mastered": schedules.filter(stage="mastered").count(),
        "learning": schedules.filter(stage="learning").count(),
        "review": schedules.filter(stage="review").count(),
    }
    return {"date": today, "counts": counts, "results": rows}


def trends(user, child_id, weeks=TREND_WEEKS):
    child = child_for(user, child_id)
    return trend_data(child, weeks)


def trend_data(child, weeks=TREND_WEEKS):
    weeks = max(1, min(weeks, 26))
    today = local_today()
    first = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    zone = ZoneInfo(settings.PRACTICE_TIME_ZONE)
    window_start = timezone.make_aware(datetime.combine(first, datetime.min.time()), zone)
    problems = Problem.objects.filter(child=child, deleted_at__isnull=True)
    attempts = (
        Attempt.objects.filter(
            item__worksheet__child=child,
            item__worksheet__deleted_at__isnull=True,
            created_at__gte=window_start,
        )
        .select_related("item")
        .order_by("created_at")[:5000]
    )
    buckets = {
        first + timedelta(days=7 * index): {
            "start": (first + timedelta(days=7 * index)).isoformat(),
            "problems_added": 0,
            "attempts": 0,
            "correct": 0,
            "wrong": 0,
            "unsure": 0,
        }
        for index in range(weeks)
    }
    for problem in problems.filter(created_at__gte=window_start).only("created_at"):
        start = problem.created_at.astimezone(zone).date() - timedelta(
            days=problem.created_at.astimezone(zone).weekday()
        )
        if start in buckets:
            buckets[start]["problems_added"] += 1
    points = {}
    for attempt in attempts:
        local = attempt.created_at.astimezone(zone).date()
        start = local - timedelta(days=local.weekday())
        bucket = buckets.get(start)
        if bucket:
            bucket["attempts"] += 1
            key = (
                "correct"
                if attempt.is_correct is True
                else "wrong"
                if attempt.is_correct is False
                else "unsure"
            )
            bucket[key] += 1
        for code in attempt.item.knowledge_points or []:
            row = points.setdefault(code, {"attempts": 0, "correct": 0})
            row["attempts"] += 1
            if attempt.is_correct is True:
                row["correct"] += 1
    total = sum(bucket["attempts"] for bucket in buckets.values())
    point_rows = []
    for code, row in sorted(points.items(), key=lambda pair: (-pair[1]["attempts"], pair[0])):
        point_rows.append(
            {
                "code": code,
                "attempts": row["attempts"],
                "correct": row["correct"],
                "accuracy": round(row["correct"] / row["attempts"], 2)
                if row["attempts"] >= MIN_POINT_SAMPLE
                else None,
                "insufficient_sample": row["attempts"] < MIN_POINT_SAMPLE,
            }
        )
    schedules = ReviewSchedule.objects.filter(child=child, problem__deleted_at__isnull=True)
    return {
        "child_id": str(child.pk),
        "weeks": [buckets[key] for key in sorted(buckets)],
        "review": {
            "due": schedules.filter(due_on__lte=today).count(),
            "mastered": schedules.filter(stage="mastered").count(),
            "learning": schedules.filter(stage="learning").count(),
            "review": schedules.filter(stage="review").count(),
        },
        "knowledge_points": point_rows,
        "sample": {
            "attempts": total,
            "min_required": MIN_SAMPLE,
            "sufficient": total >= MIN_SAMPLE,
            "note": "作答样本少于 10 次，仅展示次数，不计算正确率。"
            if total < MIN_SAMPLE
            else "正确率按自评或结构核验结果统计。",
        },
    }


def create_export(user, data):
    child = child_for(user, data["child_id"], manage=True)
    worksheet = None
    if data["kind"] == "worksheet":
        worksheet = get_object_or_404(Worksheet, pk=data["worksheet_id"], deleted_at__isnull=True)
        if worksheet.child_id != child.pk:
            raise AppError("SCOPE_MISMATCH", "题单与孩子不一致。", 400)
    ticket = ExportTicket.objects.create(
        kind=data["kind"],
        child=child,
        worksheet=worksheet,
        expires_at=timezone.now() + timedelta(minutes=EXPORT_MINUTES),
        actor=user,
    )
    audit(user, "export_ticket_created", ticket, child.family, reason=data["kind"])
    return ticket


def ticket_for(user, nonce):
    ticket = get_object_or_404(
        ExportTicket.objects.select_related("child", "worksheet"), nonce=nonce
    )
    child_for(user, ticket.child_id, manage=True)
    if ticket.revoked_at is not None or ticket.expires_at <= timezone.now():
        raise AppError("EXPORT_EXPIRED", "导出链接已失效，请重新生成。", 410)
    if ticket.child.deleted_at is not None:
        raise AppError("EXPORT_EXPIRED", "学习档案已删除，导出不可用。", 410)
    if ticket.worksheet_id and ticket.worksheet.deleted_at is not None:
        raise AppError("EXPORT_EXPIRED", "题单已删除，导出不可用。", 410)
    return ticket


def safe_name(value):
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", value)[:40] or "export"


def cell(value):
    """Neutralise spreadsheet formula injection without changing display text."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def worksheet_csv(worksheet):
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["题号", "题目", "答案", "知识点", "来源"])
    for item in worksheet.items.order_by("position"):
        available = item_source_available(item)
        writer.writerow(
            [
                item.position,
                cell(item.text) if available else "来源已不可用",
                cell(item.answer) if available else "",
                cell("、".join(item.knowledge_points)),
                {"problem": "错题本", "bank": "授权题库", "variant": "变式草稿"}[item.origin],
            ]
        )
    return buffer.getvalue()


def worksheet_html(worksheet, today):
    from apps.question_bank.models import QuestionBankItem

    bank_ids = [item.bank_item_id for item in worksheet.items.all() if item.bank_item_id]
    library = {
        row.pk: row
        for row in QuestionBankItem.objects.select_related("source").filter(pk__in=bank_ids)
    }
    rows = []
    for item in worksheet.items.order_by("position"):
        available = item_source_available(item)
        text = html.escape(item.text) if available else "来源已变更或不可用，已隐藏内容。"
        answer = html.escape(item.answer) if available else ""
        explanation = html.escape(item.explanation) if available else ""
        points = "、".join(item.knowledge_points)
        credit = ""
        if available and item.bank_item_id in library:
            source = library[item.bank_item_id].source
            credit = "".join(
                [
                    '<p class="meta">来源：',
                    html.escape(source.name),
                    " · ",
                    html.escape(source.source_reference),
                    " · 许可：",
                    html.escape(source.license_name),
                    " · 署名：",
                    html.escape(source.attribution),
                    "</p>",
                ]
            )
        rows.append(
            f'<section class="q"><h2>第 {item.position} 题</h2>'
            f'<p class="text">{text}</p>'
            f'<p class="meta">{html.escape(points)}</p>{credit}'
            f"<details><summary>答案与解析</summary><p>{answer}</p>"
            f'<p class="meta">{explanation}</p></details></section>'
        )
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:\">"
    )
    style = """
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
margin:0;padding:24px;color:#1d2b22;background:#fff;line-height:1.8}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 8px;color:#315b45}
.meta{color:#5c6b60;font-size:12px;margin:4px 0}
.q{border-top:1px solid #dce2d8;padding:16px 0;break-inside:avoid}
.text{white-space:pre-wrap;overflow-wrap:anywhere}
details summary{cursor:pointer;color:#315b45;font-size:13px}
footer{margin-top:24px;color:#5c6b60;font-size:12px}
@media print{body{padding:0}details{display:block}details>summary{display:none}}
@page{margin:16mm}
"""
    meta = (
        f'<p class="meta">{html.escape(worksheet.child.nickname)} · '
        f"导出日期 {today.isoformat()} · 共 {worksheet.items.count()} 题</p>"
    )
    footer = (
        "<footer>本导出由家长账号生成，包含私人学习内容，请勿公开传播。"
        "授权题库题目的来源、许可与署名随题展示。</footer>"
    )
    return "".join(
        [
            '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n',
            csp,
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
            f"<title>{html.escape(worksheet.title)}</title>\n<style>",
            style,
            "</style></head><body>\n",
            f"<h1>{html.escape(worksheet.title)}</h1>\n",
            meta,
            "\n",
            "".join(rows),
            "\n",
            footer,
            "\n</body></html>",
        ]
    )


def summary_csv(child, rows):
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["孩子", "统计口径", "值"])
    for label, value in rows:
        writer.writerow([cell(child.nickname), cell(label), cell(value)])
    writer.writerow([])
    writer.writerow(["题目", "题干", "知识点", "复习阶段", "下次复习", "连续答对", "遗忘次数"])
    for problem in (
        Problem.objects.filter(child=child, deleted_at__isnull=True)
        .select_related("current_text")
        .order_by("created_at")
    ):
        schedule = ReviewSchedule.objects.filter(child=child, problem=problem).first()
        writer.writerow(
            [
                str(problem.pk),
                cell(problem.current_text.text if problem.current_text else ""),
                cell("、".join(problem.knowledge_points)),
                schedule.stage if schedule else "new",
                schedule.due_on.isoformat() if schedule else "",
                schedule.streak if schedule else 0,
                schedule.lapses if schedule else 0,
            ]
        )
    return buffer.getvalue()


def render_export(ticket, fmt="html"):
    if ticket.kind == "worksheet":
        if fmt == "csv":
            return worksheet_csv(ticket.worksheet), "text/csv; charset=utf-8", "csv"
        return worksheet_html(ticket.worksheet, local_today()), "text/html; charset=utf-8", "html"
    data = trend_data(ticket.child)
    rows = [
        ("统计周数", len(data["weeks"])),
        ("作答次数", data["sample"]["attempts"]),
        ("样本是否充分", "是" if data["sample"]["sufficient"] else "否"),
        ("待复习", data["review"]["due"]),
        ("已掌握", data["review"]["mastered"]),
        ("学习中", data["review"]["learning"]),
    ]
    for bucket in data["weeks"]:
        rows.append((f"周 {bucket['start']} 作答", bucket["attempts"]))
    return summary_csv(ticket.child, rows), "text/csv; charset=utf-8", "csv"


def cleanup_exports(now=None):
    now = now or timezone.now()
    ExportTicket.objects.filter(
        Q(expires_at__lt=now - timedelta(days=1)) | Q(revoked_at__lt=now - timedelta(days=1))
    ).delete()
