from django.contrib import admin
from django.db import transaction

from apps.entitlements.admin import AuditedAdmin

from .models import BudgetPolicy, PriceVersion


@admin.register(BudgetPolicy)
class PolicyAdmin(AuditedAdmin):
    list_display = [
        "key",
        "platform_enabled",
        "halted",
        "currency",
        "day_limit",
        "month_limit",
        "lifetime_limit",
    ]

    def has_add_permission(self, request):
        return not BudgetPolicy.objects.exists() and super().has_add_permission(request)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        # Lock before form validation, so an old form cannot clear a newly tripped circuit.
        with transaction.atomic():
            BudgetPolicy.objects.select_for_update().filter(pk=object_id).first()
            return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(PriceVersion)
class PriceAdmin(AuditedAdmin):
    list_display = ["model", "currency", "valid_from", "valid_until", "bound_reviewed"]

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)
