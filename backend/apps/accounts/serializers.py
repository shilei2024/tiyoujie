from rest_framework import serializers

from .models import ChildProfile, Family, FamilyMember, GuardianConsent


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["存在不支持的字段"]})
        return super().to_internal_value(data)


class CodeInput(StrictSerializer):
    code = serializers.CharField(max_length=256)


class DevInput(StrictSerializer):
    identity = serializers.RegexField(r"^[a-zA-Z0-9_-]{3,32}$")


class RefreshInput(StrictSerializer):
    refresh_token = serializers.CharField(max_length=256)


class FamilyInput(StrictSerializer):
    name = serializers.CharField(max_length=40)


class ChildInput(StrictSerializer):
    family_id = serializers.UUIDField(required=False)
    nickname = serializers.CharField(max_length=32)
    grade = serializers.IntegerField(min_value=1, max_value=12, allow_null=True, required=False)
    semester = serializers.ChoiceField(choices=["", "上学期", "下学期"], required=False)
    textbook = serializers.CharField(max_length=40, allow_blank=True, required=False)


class ChildCreateInput(ChildInput):
    family_id = serializers.UUIDField()
    guardian_confirmed = serializers.BooleanField()
    notice_version = serializers.CharField(max_length=32)


class ConsentInput(StrictSerializer):
    scope = serializers.ChoiceField(choices=["profile", "deepseek", "kimi"])
    notice_version = serializers.CharField(max_length=32)


class InvitationInput(StrictSerializer):
    role = serializers.ChoiceField(choices=["guardian", "student"])
    child_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=20, allow_empty=False
    )


class AcceptInput(StrictSerializer):
    invitation_token = serializers.CharField(max_length=256)


class ConfirmInput(StrictSerializer):
    confirm = serializers.BooleanField()


class FamilyOutput(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    def get_role(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return (
            FamilyMember.objects.filter(family=obj, user=request.user, active=True)
            .values_list("role", flat=True)
            .first()
        )

    class Meta:
        model = Family
        fields = ["id", "name", "owner_id", "role", "created_at"]


class ChildOutput(serializers.ModelSerializer):
    class Meta:
        model = ChildProfile
        fields = ["id", "family_id", "nickname", "grade", "semester", "textbook", "created_at"]


class ConsentOutput(serializers.ModelSerializer):
    class Meta:
        model = GuardianConsent
        fields = ["id", "scope", "notice_version", "created_at", "revoked_at"]
