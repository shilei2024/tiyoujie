from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.security import rate_limit
from apps.accounts.serializers import StrictSerializer
from apps.accounts.views import page, validated
from apps.problems.services import problem_for

from .models import KnowledgePoint, VariantDraft
from .serializers import ItemOutput
from .services import create_variant, similar, source_usable, trusted_items


class Filters(StrictSerializer):
    q = serializers.CharField(max_length=80, required=False, allow_blank=True)
    knowledge_point = serializers.SlugField(max_length=48, required=False)
    grade = serializers.IntegerField(min_value=1, max_value=12, required=False)
    difficulty = serializers.IntegerField(min_value=1, max_value=5, required=False)
    question_type = serializers.CharField(max_length=48, required=False)
    solution_structure = serializers.CharField(max_length=64, required=False)


class Points(APIView):
    def get(self, request):
        return Response(
            {
                "results": list(
                    KnowledgePoint.objects.filter(enabled=True)
                    .order_by("code")
                    .values("code", "name")[:1000]
                )
            }
        )


class Similar(APIView):
    def get(self, request, pk):
        rate_limit(request, "bank_search")
        output = similar(request.user, pk, validated(Filters, request.query_params))
        output["results"] = [
            {**ItemOutput(item).data, "match_reasons": reasons}
            for item, reasons in output["results"]
        ]
        return Response(output)


class Item(APIView):
    def get(self, request, pk):
        item = get_object_or_404(trusted_items(), pk=pk)
        if not source_usable(item.source) or item.content_hash != item.content_digest():
            from django.http import Http404

            raise Http404()
        return Response(ItemOutput(item).data)


class VariantInput(StrictSerializer):
    bank_item_id = serializers.UUIDField()
    text_version_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=1)
    intent = serializers.ChoiceField(choices=["numbers", "conditions", "reverse", "context"])


class VariantOutput(serializers.ModelSerializer):
    payload = serializers.SerializerMethodField()
    stale = serializers.SerializerMethodField()
    source_available = serializers.SerializerMethodField()

    def get_stale(self, draft):
        return draft.problem.current_text_id != draft.text_version_id

    def get_source_available(self, draft):
        item = trusted_items().filter(pk=draft.bank_item_id, revision=draft.bank_revision).first()
        return bool(item and source_usable(item.source))

    def get_payload(self, draft):
        return draft.payload if self.get_source_available(draft) else None

    class Meta:
        model = VariantDraft
        fields = [
            "id",
            "created_at",
            "text_version_id",
            "bank_item_id",
            "bank_revision",
            "intent",
            "payload",
            "generator",
            "verification_status",
            "stale",
            "source_available",
        ]


class Variants(APIView):
    def get(self, request, pk):
        problem_for(request.user, pk)
        query = (
            VariantDraft.objects.filter(problem_id=pk)
            .select_related("problem")
            .order_by("-created_at", "-id")
        )
        return page(request, query, VariantOutput)

    def post(self, request, pk):
        rate_limit(request, "variant_draft")
        draft = create_variant(
            request.user,
            pk,
            validated(VariantInput, request.data),
            request.headers.get("Idempotency-Key", ""),
        )
        return Response(VariantOutput(draft).data, status=201)
