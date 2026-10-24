from datetime import date

from django.db.models import Q
from django.http import HttpResponse
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.security import rate_limit
from apps.accounts.serializers import ConfirmInput
from apps.accounts.views import family_query, page, validated
from config.errors import AppError

from .serializers import (
    AssetOutput,
    AttachInput,
    CreateInput,
    ProblemOutput,
    TextInput,
    TextOutput,
    TransformInput,
    UpdateInput,
)
from .services import (
    asset_for,
    attach_asset,
    create_problem,
    delete_problem,
    detach_asset,
    list_problems,
    problem_for,
    save_text,
    transform_asset,
    update_problem,
    upload_asset,
)
from .storage import storage


class Problems(APIView):
    def get(self, request):
        query = list_problems(request.user, family_query(request))
        for field in ("chapter", "error_type"):
            if request.query_params.get(field):
                query = query.filter(**{field: request.query_params[field][:64]})
        if request.query_params.get("child_id"):
            from uuid import UUID

            try:
                query = query.filter(child_id=UUID(request.query_params["child_id"]))
            except ValueError:
                raise AppError("INVALID_REQUEST", "孩子标识无效。", 400) from None
        if request.query_params.get("q"):
            value = request.query_params["q"][:100]
            query = query.filter(
                Q(text_versions__text__icontains=value) | Q(chapter__icontains=value)
            ).distinct()
        try:
            if request.query_params.get("grade"):
                grade = int(request.query_params["grade"])
                if not 1 <= grade <= 12:
                    raise ValueError()
                query = query.filter(child__grade=grade)
            for name, lookup in (
                ("date_from", "mistake_date__gte"),
                ("date_to", "mistake_date__lte"),
            ):
                if request.query_params.get(name):
                    query = query.filter(**{lookup: date.fromisoformat(request.query_params[name])})
        except ValueError:
            raise AppError("FILTER_INVALID", "日期或年级筛选参数无效。", 400) from None
        if request.query_params.get("knowledge_point"):
            query = query.filter(
                knowledge_points__contains=[request.query_params["knowledge_point"][:40]]
            )
        return page(
            request,
            query.select_related("current_text").order_by("-created_at", "-id"),
            ProblemOutput,
        )

    def post(self, request):
        rate_limit(request, "problem")
        return Response(
            ProblemOutput(
                create_problem(request.user, dict(validated(CreateInput, request.data)))
            ).data,
            status=201,
        )


class ProblemDetail(APIView):
    def get(self, request, pk):
        return Response(ProblemOutput(problem_for(request.user, pk)).data)

    def patch(self, request, pk):
        return Response(
            ProblemOutput(
                update_problem(request.user, pk, dict(validated(UpdateInput, request.data)))
            ).data
        )

    def delete(self, request, pk):
        if not validated(ConfirmInput, request.data)["confirm"]:
            raise AppError("CONFIRM_REQUIRED", "请确认删除。", 400)
        delete_problem(request.user, pk)
        return Response({"status": "cleanup_pending"}, status=202)


class ProblemUpdate(ProblemDetail):
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        return self.patch(request, pk)


class TextVersions(APIView):
    def get(self, request, pk):
        problem = problem_for(request.user, pk)
        return page(request, problem.text_versions.order_by("-number"), TextOutput)


class ProblemText(APIView):
    def post(self, request, pk):
        return Response(
            ProblemOutput(save_text(request.user, pk, validated(TextInput, request.data))).data
        )

    patch = post


class UploadAsset(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        rate_limit(request, "upload")
        problem_for(request.user, pk, manage=True)
        if set(request.data) != {"file"} or len(request.FILES.getlist("file")) != 1:
            raise AppError("UPLOAD_INVALID", "每次只能上传一张图片。", 400)
        return Response(
            AssetOutput(upload_asset(request.user, pk, request.FILES["file"])).data, status=201
        )


class AttachAsset(APIView):
    def post(self, request, pk):
        data = validated(AttachInput, request.data)
        return Response(
            ProblemOutput(
                attach_asset(request.user, pk, data["asset_id"], data["expected_revision"])
            ).data
        )


class AssetContent(APIView):
    def get(self, request, pk):
        asset = asset_for(request.user, pk)
        try:
            content = storage().read(asset.object.object_key)
        except OSError:
            raise AppError("STORAGE_UNAVAILABLE", "图片暂不可用。", 503) from None
        result = HttpResponse(content, content_type="image/jpeg")
        result["Content-Disposition"] = 'inline; filename="image.jpg"'
        result["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return result


class DetachAsset(APIView):
    def post(self, request, pk, asset_id):
        from .serializers import DetachInput

        data = validated(DetachInput, request.data)
        return Response(
            ProblemOutput(detach_asset(request.user, pk, asset_id, data["expected_revision"])).data
        )


class TransformAsset(APIView):
    def post(self, request, pk):
        rate_limit(request, "upload")
        results = transform_asset(request.user, pk, validated(TransformInput, request.data))
        return Response(
            {
                "results": [
                    {"problem_id": problem.pk, "asset": AssetOutput(asset).data}
                    for problem, asset in results
                ]
            },
            status=201,
        )
