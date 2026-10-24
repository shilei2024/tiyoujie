from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import family_for
from apps.accounts.serializers import StrictSerializer
from apps.accounts.views import family_query

from .models import EntitlementGrant, FamilyNotification, PromotionCampaign
from .services import child_limit, claim, eligible


class GrantOutput(serializers.ModelSerializer):
    effective_status = serializers.SerializerMethodField()

    def get_effective_status(self, obj):
        if obj.revoked_at:
            return "revoked"
        return "active" if obj.starts_at <= timezone.now() < obj.expires_at else "expired"

    class Meta:
        model = EntitlementGrant
        fields = ["id", "features", "starts_at", "expires_at", "effective_status"]


class ClaimInput(StrictSerializer):
    family_id = serializers.UUIDField()


class EntitlementsMe(APIView):
    def get(self, request):
        family = family_for(request.user, family_query(request))
        grants = EntitlementGrant.objects.filter(family=family).order_by("created_at")
        return Response(
            {
                "grants": GrantOutput(grants, many=True).data,
                "child_profile_limit": child_limit(family),
                "ai_mode": "disabled",
                "automatic_billing": False,
            }
        )


class EligibleCampaigns(APIView):
    def get(self, request):
        family = family_for(request.user, family_query(request), owner=True)
        now = timezone.now()
        results = [
            {
                "id": item.pk,
                "name": item.name,
                "duration_months": item.duration_months,
                "features": item.features,
                "child_profile_limit": item.child_profile_limit,
            }
            for item in PromotionCampaign.objects.filter(
                status="active", window_start__lte=now, window_end__gt=now
            )
            if eligible(request.user, family, item, now)
            and (
                item.capacity is None
                or EntitlementGrant.objects.filter(campaign=item).count() < item.capacity
            )
        ]
        return Response({"results": results})


class ClaimCampaign(APIView):
    def post(self, request, pk):
        data = ClaimInput(data=request.data)
        data.is_valid(raise_exception=True)
        result = claim(request.user, data.validated_data["family_id"], pk)
        return Response(GrantOutput(result).data)


class Notifications(APIView):
    def get(self, request):
        family = family_for(request.user, family_query(request), owner=True)
        return Response(
            {
                "results": list(
                    FamilyNotification.objects.filter(family=family)
                    .order_by("-created_at")
                    .values("id", "message", "created_at")[:50]
                )
            }
        )
