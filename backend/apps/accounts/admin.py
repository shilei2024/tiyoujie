from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.entitlements.admin import ReasonForm

from .models import AuditEvent, AuthSession

User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class AccountStatusAdmin(admin.ModelAdmin):
    form = ReasonForm
    fields = ["username", "is_active", "is_staff", "is_superuser", "reason"]
    readonly_fields = ["username", "is_staff", "is_superuser"]
    list_display = ["id", "is_active", "is_staff"]

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if not obj.is_active:
                AuthSession.objects.filter(user=obj).update(revoked_at=timezone.now())
            AuditEvent.objects.create(
                actor_id=request.user.pk,
                action="admin_account_status_changed",
                object_id=str(obj.pk),
                reason=form.cleaned_data["reason"],
            )
