from rest_framework import serializers

from apps.accounts.serializers import StrictSerializer

from .models import Worksheet


class WorksheetInput(StrictSerializer):
    child_id = serializers.UUIDField()
    title = serializers.CharField(max_length=40)


class ItemInput(StrictSerializer):
    origin = serializers.ChoiceField(choices=["problem", "bank", "variant"])
    problem_id = serializers.UUIDField(required=False, allow_null=True)
    bank_item_id = serializers.UUIDField(required=False, allow_null=True)
    variant_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        expected = {
            "problem": ("problem_id",),
            "bank": ("bank_item_id",),
            "variant": ("variant_id",),
        }[data["origin"]]
        supplied = {
            name
            for name in ("problem_id", "bank_item_id", "variant_id")
            if data.get(name) is not None
        }
        if supplied != set(expected):
            raise serializers.ValidationError({"non_field_errors": ["题目类型与所选来源不匹配"]})
        return data


class AttemptInput(StrictSerializer):
    answer = serializers.CharField(max_length=2000, allow_blank=True)
    self_grade = serializers.ChoiceField(choices=["correct", "wrong", "unsure"])
    duration_seconds = serializers.IntegerField(min_value=0, max_value=7200, required=False)


class GradeInput(StrictSerializer):
    grade = serializers.ChoiceField(choices=["correct", "wrong", "unsure"])


class ExportInput(StrictSerializer):
    kind = serializers.ChoiceField(choices=["worksheet", "summary"])
    child_id = serializers.UUIDField()
    worksheet_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        if data["kind"] == "worksheet" and not data.get("worksheet_id"):
            raise serializers.ValidationError({"worksheet_id": ["导出题单时必填"]})
        if data["kind"] == "summary" and data.get("worksheet_id"):
            raise serializers.ValidationError({"worksheet_id": ["概览导出不带题单"]})
        return data


class WorksheetOutput(serializers.ModelSerializer):
    child_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Worksheet
        fields = ["id", "child_id", "title", "revision", "created_at"]


class AttemptOutput(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    number = serializers.IntegerField(read_only=True)
    answer = serializers.CharField(read_only=True)
    self_grade = serializers.CharField(read_only=True)
    is_correct = serializers.BooleanField(read_only=True, allow_null=True)
    graded_by = serializers.CharField(read_only=True)
    duration_seconds = serializers.IntegerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
