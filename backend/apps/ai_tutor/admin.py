from django.contrib import admin

from apps.accounts.models import AuditEvent


@admin.register(AuditEvent)
class PlatformOperationsAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "object_id", "reason"]
    list_filter = ["action", "created_at"]
    readonly_fields = ["created_at", "action", "object_id", "reason"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(action__startswith="platform_")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
