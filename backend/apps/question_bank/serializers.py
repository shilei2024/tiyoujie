import json

from rest_framework import serializers

from apps.accounts.serializers import StrictSerializer

from .models import KnowledgePoint, QuestionBankItem


class ItemInput(StrictSerializer):
    text = serializers.CharField(max_length=4000)
    answer = serializers.CharField(max_length=1000)
    explanation = serializers.CharField(max_length=4000)
    answer_source = serializers.CharField(max_length=500)
    explanation_source = serializers.CharField(max_length=500)
    grade = serializers.IntegerField(min_value=1, max_value=12)
    question_type = serializers.CharField(max_length=48)
    solution_structure = serializers.CharField(max_length=64)
    difficulty = serializers.IntegerField(min_value=1, max_value=5)
    knowledge_points = serializers.ListField(
        child=serializers.SlugField(max_length=48), min_length=1, max_length=8
    )
    math_spec = serializers.JSONField(default=dict)

    def validate_knowledge_points(self, value):
        if len(value) != len(set(value)) or KnowledgePoint.objects.filter(
            code__in=value, enabled=True
        ).count() != len(value):
            raise serializers.ValidationError("知识点必须来自启用的字典且不可重复。")
        return sorted(value)

    def validate(self, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(raw) > 14000 or any(
            marker in raw.lower()
            for marker in ("<script", "<svg", "javascript:", "<iframe", "data:text/html")
        ):
            raise serializers.ValidationError("内容过长或包含不支持的标记。")
        spec = data["math_spec"]
        if not isinstance(spec, dict) or len(json.dumps(spec)) > 3000:
            raise serializers.ValidationError("数学描述必须为有界 JSON 对象。")
        # Math is verified separately; unsupported types can enter the manual review queue.
        if data["text"].count("$") % 2:
            raise serializers.ValidationError("公式分隔符不成对，请校对。")
        return data


class ImportInput(StrictSerializer):
    source_id = serializers.UUIDField()
    items = ItemInput(many=True, min_length=1, max_length=20)


class ItemOutput(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    verification_scope = serializers.SerializerMethodField()

    def get_source(self, item):
        source = item.source
        return {
            name: getattr(source, name)
            for name in [
                "name",
                "source_type",
                "source_reference",
                "license_name",
                "attribution",
                "usage_conditions",
            ]
        } | {"authorization_status": "reviewed", "valid_until": source.valid_until.isoformat()}

    def get_verification_scope(self, item):
        from .math_verifier import SCOPE

        return (
            SCOPE
            if item.verification_status == "machine_checked"
            else "审核员已复核当前版本的题干、答案与解析。"
        )

    class Meta:
        model = QuestionBankItem
        fields = [
            "id",
            "revision",
            "text",
            "answer",
            "explanation",
            "answer_source",
            "explanation_source",
            "grade",
            "question_type",
            "solution_structure",
            "difficulty",
            "knowledge_points",
            "verification_status",
            "verification_method",
            "verified_at",
            "source",
            "verification_scope",
        ]
