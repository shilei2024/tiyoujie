import hmac
from uuid import UUID

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import AppError

from .access import child_for, children_for, family_for, visible_families
from .models import AuthSession, ChildProfile, DeletionRequest, FamilyMember, GuardianConsent
from .security import digest, issue_session, rate_limit, refresh_session
from .serializers import (
    AcceptInput,
    ChildCreateInput,
    ChildInput,
    ChildOutput,
    CodeInput,
    ConfirmInput,
    ConsentInput,
    ConsentOutput,
    DevInput,
    FamilyInput,
    FamilyOutput,
    InvitationInput,
    RefreshInput,
)
from .services import (
    accept_invitation,
    audit,
    create_child,
    create_family,
    invite,
    request_deletion,
    revoke_member,
)
from .wechat import exchange_code, identity_user


def validated(serializer, data):
    item = serializer(data=data)
    item.is_valid(raise_exception=True)
    return item.validated_data


def family_query(request):
    try:
        return UUID(request.query_params.get("family_id", ""))
    except (ValueError, TypeError):
        raise AppError("FAMILY_REQUIRED", "请先选择家庭。", 400) from None


def page(request, query, serializer):
    try:
        number = int(request.query_params.get("page", "1"))
        if number < 1:
            raise ValueError()
        paginator = Paginator(query, 20)
        result = paginator.page(number)
    except (ValueError, EmptyPage):
        raise AppError("PAGE_INVALID", "分页参数无效。", 400) from None
    return Response(
        {
            "count": paginator.count,
            "page": number,
            "next": result.next_page_number() if result.has_next() else None,
            "results": serializer(result, many=True, context={"request": request}).data,
        }
    )


class Capabilities(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(
            {
                "dev_login_available": settings.APP_ENV == "dev" and settings.DEV_LOGIN_ENABLED,
                "wechat_configured": bool(settings.WECHAT_APP_ID and settings.WECHAT_APP_SECRET),
                "guardian_notice_version": settings.GUARDIAN_NOTICE_VERSION,
            }
        )


class DevLogin(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if settings.APP_ENV not in {"dev", "test"} or not settings.DEV_LOGIN_ENABLED:
            raise NotFound()
        rate_limit(request)
        values = validated(DevInput, request.data)
        user = identity_user("dev", "local", values["identity"])
        return Response(issue_session(user, is_test=True))


class WechatLogin(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        rate_limit(request)
        values = validated(CodeInput, request.data)
        subject = exchange_code(values["code"])
        return Response(issue_session(identity_user("wechat", settings.WECHAT_APP_ID, subject)))


class Refresh(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        rate_limit(request)
        return Response(refresh_session(validated(RefreshInput, request.data)["refresh_token"]))


class Logout(APIView):
    def post(self, request):
        AuthSession.objects.filter(pk=request.auth.pk).update(revoked_at=timezone.now())
        return Response(status=204)


class Me(APIView):
    def get(self, request):
        return Response({"id": request.user.pk, "is_test_login": request.auth.is_test_login})


class Families(APIView):
    def get(self, request):
        return page(request, visible_families(request.user), FamilyOutput)

    def post(self, request):
        rate_limit(request, "family")
        data = validated(FamilyInput, request.data)
        return Response(FamilyOutput(create_family(request.user, data["name"])).data, status=201)


class FamilyDetail(APIView):
    def get(self, request, pk):
        return Response(FamilyOutput(family_for(request.user, pk)).data)

    def patch(self, request, pk):
        family = family_for(request.user, pk, owner=True)
        family.name = validated(FamilyInput, request.data)["name"]
        with transaction.atomic():
            family.save(update_fields=["name"])
            audit(request.user, "family_updated", family, family)
        return Response(FamilyOutput(family).data)


class Children(APIView):
    def get(self, request):
        return page(
            request,
            children_for(request.user, family_query(request)).order_by("created_at", "id"),
            ChildOutput,
        )

    def post(self, request):
        data = validated(ChildCreateInput, request.data)
        return Response(ChildOutput(create_child(request.user, dict(data))).data, status=201)


class ChildDetail(APIView):
    def get(self, request, pk):
        return Response(ChildOutput(child_for(request.user, pk)).data)

    def patch(self, request, pk):
        child = child_for(request.user, pk, manage=True)
        data = ChildInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        if "family_id" in data.validated_data:
            raise AppError("FAMILY_IMMUTABLE", "不能转移档案归属。", 400)
        if not GuardianConsent.objects.filter(
            child=child, scope="profile", revoked_at__isnull=True
        ).exists():
            raise AppError("CONSENT_REQUIRED", "档案管理授权已撤回，请重新授权。", 403)
        with transaction.atomic():
            child = get_object_or_404(
                ChildProfile.objects.select_for_update(), pk=child.pk, deleted_at__isnull=True
            )
            for name, value in data.validated_data.items():
                setattr(child, name, value)
            if data.validated_data:
                child.save(update_fields=list(data.validated_data))
            audit(request.user, "child_updated", child, child.family)
        return Response(ChildOutput(child).data)

    def delete(self, request, pk):
        if not validated(ConfirmInput, request.data)["confirm"]:
            raise AppError("CONFIRM_REQUIRED", "需要确认删除。", 400)
        return Response(
            request_deletion(request.user, child_for(request.user, pk, manage=True)), status=202
        )


class ChildUpdate(ChildDetail):
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        return self.patch(request, pk)


class Consents(APIView):
    def get(self, request, pk):
        child = child_for(request.user, pk, manage=True)
        return Response(
            {
                "results": ConsentOutput(
                    GuardianConsent.objects.filter(child=child).order_by("created_at"), many=True
                ).data
            }
        )

    def post(self, request, pk):
        child = child_for(request.user, pk, manage=True)
        data = validated(ConsentInput, request.data)
        if data["notice_version"] != settings.GUARDIAN_NOTICE_VERSION:
            raise AppError("NOTICE_CHANGED", "请阅读最新版告知。", 409)
        with transaction.atomic():
            get_object_or_404(
                ChildProfile.objects.select_for_update(), pk=child.pk, deleted_at__isnull=True
            )
            GuardianConsent.objects.filter(
                child=child, scope=data["scope"], revoked_at__isnull=True
            ).update(revoked_at=timezone.now())
            consent = GuardianConsent.objects.create(child=child, guardian=request.user, **data)
            audit(request.user, "consent_granted", consent, child.family)
        return Response(ConsentOutput(consent).data, status=201)


class RevokeConsent(APIView):
    def delete(self, request, pk, consent_id):
        child = child_for(request.user, pk, manage=True)
        consent = get_object_or_404(GuardianConsent, pk=consent_id, child=child)
        with transaction.atomic():
            consent.revoked_at = timezone.now()
            consent.save(update_fields=["revoked_at"])
            audit(request.user, "consent_revoked", consent, child.family)
        return Response(status=204)


class Invitations(APIView):
    def post(self, request, pk):
        rate_limit(request, "invitation")
        data = validated(InvitationInput, request.data)
        return Response(invite(request.user, pk, data["role"], data["child_ids"]), status=201)


class AcceptInvitation(APIView):
    def post(self, request):
        rate_limit(request, "invitation")
        return Response(
            FamilyOutput(
                accept_invitation(
                    request.user, validated(AcceptInput, request.data)["invitation_token"]
                )
            ).data
        )


class Members(APIView):
    def get(self, request, pk):
        family_for(request.user, pk, owner=True)
        return Response(
            {
                "results": list(
                    FamilyMember.objects.filter(family_id=pk, active=True).values(
                        "id", "user_id", "role"
                    )
                )
            }
        )


class MemberDetail(APIView):
    def delete(self, request, pk):
        member = get_object_or_404(FamilyMember, pk=pk)
        revoke_member(request.user, member)
        return Response(status=204)


class AccountDeletion(APIView):
    def post(self, request):
        if not validated(ConfirmInput, request.data)["confirm"]:
            raise AppError("CONFIRM_REQUIRED", "需要确认注销。", 400)
        return Response(request_deletion(request.user), status=202)


class DeletionStatus(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk):
        entry = get_object_or_404(DeletionRequest, pk=pk)
        receipt = request.headers.get("X-Deletion-Receipt", "")
        if not 1 <= len(receipt) <= 256 or not hmac.compare_digest(
            entry.receipt_hash, digest(receipt)
        ):
            raise NotFound()
        return Response(
            {"task_id": entry.pk, "status": entry.status, "completed_at": entry.completed_at}
        )
