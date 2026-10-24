from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from .models import ChildProfile, Family, FamilyMember


def member_for(user, family_id):
    return get_object_or_404(
        FamilyMember.objects.select_related("family"), family_id=family_id, user=user, active=True
    )


def family_for(user, family_id, owner=False):
    member = member_for(user, family_id)
    if owner and member.family.owner_id != user.pk:
        raise PermissionDenied()
    return member.family


def children_for(user, family_id):
    family = family_for(user, family_id)
    result = ChildProfile.objects.filter(family=family, deleted_at__isnull=True)
    if family.owner_id != user.pk:
        result = result.filter(
            childaccessgrant__member__user=user, childaccessgrant__member__active=True
        )
    return result.distinct()


def child_for(user, child_id, manage=False):
    child = get_object_or_404(ChildProfile, pk=child_id, deleted_at__isnull=True)
    member = member_for(user, child.family_id)
    child = get_object_or_404(children_for(user, child.family_id), pk=child.pk)
    if manage and member.role != "guardian":
        raise PermissionDenied()
    return child


def visible_families(user):
    return (
        Family.objects.filter(Q(members__user=user) & Q(members__active=True))
        .distinct()
        .order_by("created_at", "id")
    )
