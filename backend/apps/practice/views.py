from uuid import UUID

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import child_for
from apps.accounts.models import FamilyMember
from apps.accounts.security import rate_limit
from apps.accounts.serializers import ConfirmInput, StrictSerializer
from apps.accounts.views import page, validated
from apps.problems.services import problem_for
from config.errors import AppError

from .models import WorksheetItem
from .serializers import (
    AttemptInput,
    AttemptOutput,
    ExportInput,
    GradeInput,
    ItemInput,
    WorksheetInput,
    WorksheetOutput,
)
from .services import (
    add_item,
    apply_review,
    create_export,
    create_worksheet,
    delete_worksheet,
    item_summary,
    list_worksheets,
    remove_item,
    render_export,
    review_queue,
    submit_attempt,
    ticket_for,
    trend_data,
    worksheet_for,
    worksheet_payload,
)


def guardian_of(user, family_id):
    return FamilyMember.objects.filter(
        family_id=family_id, user=user, active=True, role="guardian"
    ).exists()


def child_id_param(request):
    try:
        return UUID(request.query_params.get("child_id", ""))
    except (ValueError, TypeError):
        raise AppError("CHILD_REQUIRED", "请先选择孩子。", 400) from None


class Worksheets(APIView):
    def get(self, request):
        query = list_worksheets(request.user, child_id_param(request))
        return page(request, query, WorksheetOutput)

    def post(self, request):
        rate_limit(request, "worksheet")
        worksheet = create_worksheet(request.user, validated(WorksheetInput, request.data))
        return Response(WorksheetOutput(worksheet).data, status=201)


class WorksheetDetail(APIView):
    def get(self, request, pk):
        worksheet = worksheet_for(request.user, pk)
        reveal = guardian_of(request.user, worksheet.child.family_id)
        return Response(worksheet_payload(worksheet, reveal))

    def delete(self, request, pk):
        worksheet_for(request.user, pk, manage=True)
        if not validated(ConfirmInput, request.data)["confirm"]:
            raise AppError("CONFIRM_REQUIRED", "请确认删除。", 400)
        delete_worksheet(request.user, pk)
        return Response({"status": "deleted"})


class WorksheetItems(APIView):
    def post(self, request, pk):
        rate_limit(request, "worksheet")
        worksheet_for(request.user, pk, manage=True)
        item = add_item(request.user, pk, validated(ItemInput, request.data))
        return Response(item_summary(item, reveal=False), status=201)


class WorksheetItemDetail(APIView):
    def get(self, request, pk, item_id):
        worksheet = worksheet_for(request.user, pk)
        item = get_object_or_404(
            WorksheetItem.objects.select_related("worksheet", "problem"),
            pk=item_id,
            worksheet=worksheet,
        )
        reveal = guardian_of(request.user, worksheet.child.family_id) or item.attempts.exists()
        data = item_summary(item, reveal=reveal)
        data["attempts"] = AttemptOutput(item.attempts.order_by("number"), many=True).data
        return Response(data)

    def delete(self, request, pk, item_id):
        remove_item(request.user, pk, item_id)
        return Response({"status": "removed"})


class WorksheetAttempts(APIView):
    def post(self, request, pk, item_id):
        rate_limit(request, "attempt")
        attempt, schedule = submit_attempt(
            request.user, item_id, validated(AttemptInput, request.data)
        )
        payload = AttemptOutput(attempt).data
        payload["review"] = (
            {
                "due_on": schedule.due_on,
                "stage": schedule.stage,
                "interval_days": schedule.interval_days,
                "streak": schedule.streak,
            }
            if schedule
            else None
        )
        return Response(payload, status=201)


class ReviewQueue(APIView):
    def get(self, request):
        child_id = child_id_param(request)
        child_for(request.user, child_id)
        return Response(review_queue(request.user, child_id))


class GradeReview(APIView):
    def post(self, request, pk):
        rate_limit(request, "review")
        problem = problem_for(request.user, pk)
        schedule = apply_review(request.user, problem, validated(GradeInput, request.data)["grade"])
        return Response(
            {
                "problem_id": str(schedule.problem_id),
                "due_on": schedule.due_on,
                "stage": schedule.stage,
                "interval_days": schedule.interval_days,
                "streak": schedule.streak,
                "lapses": schedule.lapses,
            }
        )


class TrendQuery(StrictSerializer):
    weeks = serializers.IntegerField(min_value=1, max_value=26, required=False)


class Trends(APIView):
    def get(self, request, pk):
        weeks = validated(TrendQuery, request.query_params).get("weeks", 8)
        return Response(trend_data(child_for(request.user, pk), weeks))


class Exports(APIView):
    def post(self, request):
        rate_limit(request, "export")
        ticket = create_export(request.user, validated(ExportInput, request.data))
        return Response(
            {
                "nonce": ticket.nonce,
                "kind": ticket.kind,
                "expires_at": ticket.expires_at,
                "url": f"/api/v1/exports/{ticket.nonce}/",
            },
            status=201,
        )


class ExportDownload(APIView):
    # File responses bypass rendering, but negotiation still needs one renderer.
    renderer_classes = [JSONRenderer]

    def get(self, request, nonce):
        ticket = ticket_for(request.user, nonce)
        fmt = request.query_params.get("file", "html")
        if fmt not in {"html", "csv"}:
            raise AppError("FORMAT_INVALID", "仅支持 html 或 csv 导出。", 400)
        body, content_type, extension = render_export(ticket, fmt)
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="export.{extension}"'
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
