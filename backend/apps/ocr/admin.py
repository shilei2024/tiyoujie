from django.contrib import admin

from apps.entitlements.admin import AuditedAdmin

from .models import OCRModel


@admin.register(OCRModel)
class ModelAdmin(AuditedAdmin):
    list_display = [
        "provider",
        "model_name",
        "enabled",
        "supports_vision",
        "analysis_enabled",
        "runtime_approved",
        "integration_verified",
    ]

    def get_readonly_fields(self, request, obj=None):
        return ["provider", "model_name"] if obj else []
