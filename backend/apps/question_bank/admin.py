import json

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.response import TemplateResponse
from django.urls import path
from rest_framework.exceptions import APIException

from apps.accounts.services import audit

from .models import KnowledgePoint, QuestionBankItem, QuestionSource, VerificationRecord
from .serializers import ItemInput
from .services import check_item, commit_import, preview_import, review_item, review_source


class WorkflowForm(forms.Form):
    operation = forms.ChoiceField(
        label="操作",
        choices=[
            ("preview", "预览导入"),
            ("commit", "确认导入（需预览令牌）"),
            ("source_review", "审核来源授权"),
            ("math_check", "运行数学核验"),
            ("item_review", "审核题目"),
        ],
    )
    payload = forms.JSONField(
        label="JSON 内容", max_length=60000, widget=forms.Textarea(attrs={"rows": 18, "cols": 100})
    )


@admin.register(QuestionSource)
class SourceAdmin(admin.ModelAdmin):
    change_list_template = "admin/question_bank/source_list.html"
    list_display = ["name", "source_type", "review_status", "revision", "valid_until"]
    list_filter = ["review_status", "source_type"]
    readonly_fields = [
        "revision",
        "review_status",
        "reviewed_digest",
        "reviewed_at",
        "reviewed_by",
        "review_reason",
    ]
    actions = None

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request.user, "bank_source_changed", obj, reason="edit" if change else "create")

    def get_urls(self):
        return [
            path(
                "workflow/",
                self.admin_site.admin_view(self.workflow),
                name="question_bank_workflow",
            )
        ] + super().get_urls()

    def workflow(self, request):
        if not request.user.has_perm("question_bank.view_questionbankitem"):
            raise PermissionDenied()
        form = WorkflowForm(request.POST or None)
        result, commit_payload, preview_rows = None, None, None
        if request.method == "POST" and form.is_valid():
            operation, data = form.cleaned_data["operation"], form.cleaned_data["payload"]
            try:
                if not isinstance(data, dict):
                    raise ValueError()
                if operation == "preview":
                    result = preview_import(request.user, data)
                    preview_rows = result["rows"]
                    commit_payload = json.dumps(
                        {"document": data, "preview_token": result["preview_token"]},
                        ensure_ascii=False,
                    )
                elif operation == "commit":
                    result = commit_import(request.user, data["document"], data["preview_token"])
                elif operation == "math_check":
                    result = check_item(request.user, data["item_id"])
                elif operation == "source_review":
                    item = review_source(
                        request.user, data["source_id"], data["decision"], data["reason"]
                    )
                    result = {"id": str(item.pk), "review_status": item.review_status}
                else:
                    flags = {
                        key: data.get(key) is True
                        for key in ["statement_checked", "answer_checked", "explanation_checked"]
                    }
                    item = review_item(
                        request.user, data["item_id"], data["decision"], data["reason"], **flags
                    )
                    result = {
                        "id": str(item.pk),
                        "review_status": item.review_status,
                        "verification_status": item.verification_status,
                    }
            except APIException as exc:
                form.add_error(
                    None, getattr(exc, "public_message", "字段未通过校验，请检查格式和知识点字典。")
                )
            except (ValueError, TypeError, KeyError, ValidationError):
                form.add_error(None, "JSON 字段不完整或格式无效，请参照运维文档。")
        context = {
            **self.admin_site.each_context(request),
            "title": "题库导入与审核工作台",
            "form": form,
            "result": json.dumps(result, ensure_ascii=False, indent=2)
            if result is not None
            else None,
            "commit_payload": commit_payload,
            "preview_rows": preview_rows,
        }
        return TemplateResponse(request, "admin/question_bank/workflow.html", context)


class ItemForm(forms.ModelForm):
    class Meta:
        model = QuestionBankItem
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        data = {field: cleaned[field] for field in ItemInput().fields if field in cleaned}
        serializer = ItemInput(data=data)
        if not serializer.is_valid():
            raise ValidationError("请检查内容、公式分隔符及启用的知识点字典。")
        return cleaned


@admin.register(QuestionBankItem)
class ItemAdmin(admin.ModelAdmin):
    form = ItemForm
    list_display = [
        "id",
        "source",
        "grade",
        "question_type",
        "review_status",
        "verification_status",
        "revision",
    ]
    list_filter = ["review_status", "verification_status", "grade", "difficulty"]
    search_fields = ["text", "answer"]
    readonly_fields = [field.name for field in QuestionBankItem._meta.fields if not field.editable]
    actions = None

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request.user, "bank_item_changed", obj, reason="content edit; review reset")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KnowledgePoint)
class PointAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "enabled"]
    search_fields = ["code", "name"]


@admin.register(VerificationRecord)
class CheckAdmin(admin.ModelAdmin):
    list_display = ["id", "item", "revision", "created_at", "actor"]
    readonly_fields = [field.name for field in VerificationRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
