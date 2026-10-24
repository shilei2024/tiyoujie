from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import member_for
from apps.accounts.security import rate_limit
from apps.accounts.serializers import StrictSerializer
from config.errors import AppError

from .models import UserProviderCredential
from .services import change_credential, credential_for, replace_credential, save_credential


class CredentialInput(StrictSerializer):
    family_id = serializers.UUIDField()
    provider = serializers.ChoiceField(choices=["deepseek", "kimi"])
    key = serializers.CharField(min_length=8, max_length=512, trim_whitespace=True, write_only=True)


class ReplaceInput(StrictSerializer):
    key = serializers.CharField(min_length=8, max_length=512, trim_whitespace=True, write_only=True)


class ToggleInput(StrictSerializer):
    enabled = serializers.BooleanField()


class CredentialOutput(serializers.ModelSerializer):
    masked_key = serializers.SerializerMethodField()

    def get_masked_key(self, obj):
        return "••••" + obj.suffix

    class Meta:
        model = UserProviderCredential
        fields = [
            "id",
            "family_id",
            "provider",
            "masked_key",
            "enabled",
            "credential_version",
            "validation_status",
            "updated_at",
        ]


def require_https(request):
    if not request.is_secure():
        raise AppError("HTTPS_REQUIRED", "密钥只能通过 HTTPS 提交，请先配置安全连接。", 400)


class CredentialsView(APIView):
    def get(self, request):
        from apps.accounts.views import family_query

        family_id = family_query(request)
        if member_for(request.user, family_id).role != "guardian":
            raise AppError("FORBIDDEN", "学生不能管理服务凭证。", 403)
        query = UserProviderCredential.objects.filter(
            family_id=family_id, owner=request.user, deleted_at__isnull=True
        ).order_by("created_at")
        return Response({"results": CredentialOutput(query, many=True).data})

    def post(self, request):
        require_https(request)
        rate_limit(request, "credential")
        data = CredentialInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        credential = save_credential(
            request.user, values["family_id"], values["provider"], values["key"]
        )
        return Response(CredentialOutput(credential).data, status=201)


class CredentialDetail(APIView):
    def get(self, request, pk):
        return Response(CredentialOutput(credential_for(request.user, pk)).data)

    def patch(self, request, pk):
        data = ToggleInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            CredentialOutput(
                change_credential(request.user, pk, enabled=data.validated_data["enabled"])
            ).data
        )

    def delete(self, request, pk):
        change_credential(request.user, pk, delete=True)
        return Response(status=204)


class CredentialState(CredentialDetail):
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        return self.patch(request, pk)


class CredentialReplace(APIView):
    def post(self, request, pk):
        require_https(request)
        rate_limit(request, "credential")
        data = ReplaceInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            CredentialOutput(replace_credential(request.user, pk, data.validated_data["key"])).data
        )
