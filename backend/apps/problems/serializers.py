from rest_framework import serializers

from apps.accounts.serializers import StrictSerializer

from .models import Asset, Problem, ProblemTextVersion


class MetadataInput(StrictSerializer):
    source = serializers.CharField(max_length=120, allow_blank=True, required=False)
    chapter = serializers.CharField(max_length=64, allow_blank=True, required=False)
    knowledge_points = serializers.ListField(
        child=serializers.CharField(max_length=40), max_length=10, required=False
    )
    error_type = serializers.CharField(max_length=32, allow_blank=True, required=False)
    mistake_date = serializers.DateField(allow_null=True, required=False)


class CreateInput(MetadataInput):
    child_id = serializers.UUIDField()


class UpdateInput(MetadataInput):
    expected_revision = serializers.IntegerField(min_value=1)


class TextInput(StrictSerializer):
    expected_revision = serializers.IntegerField(min_value=1)
    text = serializers.CharField(max_length=20000, trim_whitespace=False)
    answer = serializers.CharField(
        max_length=10000, allow_blank=True, trim_whitespace=False, default=""
    )
    confirmed = serializers.BooleanField()
    parent_id = serializers.UUIDField(allow_null=True, required=False)


class RegionInput(StrictSerializer):
    x = serializers.IntegerField(min_value=0)
    y = serializers.IntegerField(min_value=0)
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    rotation = serializers.ChoiceField(choices=[0, 90, 180, 270], default=0)


class TransformInput(StrictSerializer):
    problem_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=1)
    regions = RegionInput(many=True, min_length=1, max_length=8)
    split = serializers.BooleanField(default=False)


class AttachInput(StrictSerializer):
    asset_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=1)


class DetachInput(StrictSerializer):
    expected_revision = serializers.IntegerField(min_value=1)


class TextOutput(serializers.ModelSerializer):
    class Meta:
        model = ProblemTextVersion
        fields = [
            "id",
            "number",
            "origin",
            "text",
            "answer",
            "confirmed",
            "parent_id",
            "confidence",
            "uncertainties",
            "created_at",
        ]


class AssetOutput(serializers.ModelSerializer):
    byte_size = serializers.IntegerField(source="object.byte_size")

    class Meta:
        model = Asset
        fields = ["id", "width", "height", "byte_size", "parent_id", "created_at"]


class ProblemOutput(serializers.ModelSerializer):
    current_text = TextOutput(read_only=True)
    assets = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    def get_assets(self, obj):
        return AssetOutput(
            Asset.objects.filter(problem_links__problem=obj, object__state="live"), many=True
        ).data

    def get_status(self, obj):
        if obj.current_text_id:
            return "confirmed"
        return "needs_review" if obj.text_versions.filter(origin="ocr").exists() else "draft"

    class Meta:
        model = Problem
        fields = [
            "id",
            "child_id",
            "source",
            "chapter",
            "knowledge_points",
            "error_type",
            "mistake_date",
            "revision",
            "status",
            "current_text",
            "assets",
            "created_at",
        ]
