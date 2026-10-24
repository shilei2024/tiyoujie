import uuid

from django import forms
from django.contrib import admin
from django.db import transaction

from apps.accounts.models import AuditEvent

from .models import EntitlementEvent, EntitlementGrant, PromotionCampaign, ResourcePolicy


class ReasonForm(forms.ModelForm):
    reason = forms.CharField(
        max_length=200, label="操作原因", help_text="必填；不要填写孩子身份信息或任何密钥。"
    )

    def clean(self):
        data = super().clean()
        if isinstance(self.instance, EntitlementGrant):
            expiry = data.get("expires_at")
            if expiry and expiry <= self.instance.starts_at:
                raise forms.ValidationError("到期时间必须晚于开始时间。")
        return data


class AuditedAdmin(admin.ModelAdmin):
    form = ReasonForm

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            AuditEvent.objects.create(
                actor_id=request.user.pk,
                action="admin_configuration_changed",
                object_id=str(obj.pk),
                reason=form.cleaned_data["reason"],
            )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PromotionCampaign)
class CampaignAdmin(AuditedAdmin):
    list_display = ["name", "status", "window_start", "window_end", "duration_months", "capacity"]


@admin.register(ResourcePolicy)
class PolicyAdmin(AuditedAdmin):
    list_display = ["key", "basic_child_limit", "max_families"]

    def has_add_permission(self, request):
        return not ResourcePolicy.objects.exists() and super().has_add_permission(request)


@admin.register(EntitlementGrant)
class GrantAdmin(AuditedAdmin):
    list_display = ["id", "family", "starts_at", "expires_at", "revoked_at"]
    readonly_fields = [
        "family",
        "campaign",
        "features",
        "child_profile_limit",
        "exclusivity_group",
        "starts_at",
    ]

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            EntitlementEvent.objects.create(
                grant=obj,
                kind="adjusted",
                node=uuid.uuid4().hex,
                reason=form.cleaned_data["reason"],
            )
