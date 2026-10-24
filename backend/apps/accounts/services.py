import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from config.errors import AppError

from .access import child_for, family_for
from .models import (
    AuditEvent,
    AuthSession,
    ChildAccessGrant,
    ChildProfile,
    DeletionRequest,
    Family,
    FamilyMember,
    GuardianConsent,
    Invitation,
)
from .security import digest


def audit(actor, action, obj, family=None, reason=""):
    AuditEvent.objects.create(
        actor_id=actor.pk if actor else None,
        action=action,
        object_id=str(obj.pk),
        family_id=family.pk if family else None,
        reason=reason,
    )


@transaction.atomic
def create_family(user, name):
    from apps.entitlements.services import policy

    get_user_model().objects.select_for_update().get(pk=user.pk)
    if Family.objects.filter(owner=user).count() >= policy().max_families:
        raise AppError("FAMILY_LIMIT", "已达到家庭数量上限。", 403)
    family = Family.objects.create(owner=user, name=name)
    FamilyMember.objects.create(family=family, user=user, role="guardian")
    audit(user, "family_created", family, family)
    return family


@transaction.atomic
def create_child(user, data):
    from apps.entitlements.services import child_limit

    confirmed, version = data.pop("guardian_confirmed", False), data.pop("notice_version", "")
    if not confirmed or version != settings.GUARDIAN_NOTICE_VERSION:
        raise AppError("CONSENT_REQUIRED", "请阅读当前监护人告知并确认。", 403)
    family_id = data.pop("family_id", None)
    if not family_id:
        raise AppError("FAMILY_REQUIRED", "请先选择家庭。", 400)
    family_for(user, family_id, owner=True)
    family = Family.objects.select_for_update().get(pk=family_id)
    if family.children.filter(deleted_at__isnull=True).count() >= child_limit(family):
        raise AppError("CHILD_LIMIT", "已达到当前权益的档案数量上限，既有档案仍可访问。", 403)
    child = ChildProfile.objects.create(family=family, **data)
    GuardianConsent.objects.create(
        child=child, guardian=user, scope="profile", notice_version=version
    )
    audit(user, "child_created", child, family)
    return child


@transaction.atomic
def invite(user, family_id, role, child_ids):
    family = family_for(user, family_id, owner=True)
    ids = list(set(child_ids))
    if family.children.filter(pk__in=ids, deleted_at__isnull=True).count() != len(ids):
        raise AppError("CHILD_SCOPE_INVALID", "邀请只能包含本家庭可用档案。", 400)
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        family=family,
        role=role,
        child_ids=[str(x) for x in ids],
        token_hash=digest(token),
        expires_at=timezone.now() + timedelta(hours=24),
    )
    audit(user, "invitation_created", invitation, family)
    return {"invitation_token": token, "expires_at": invitation.expires_at}


@transaction.atomic
def accept_invitation(user, token):
    entry = Invitation.objects.filter(token_hash=digest(token)).first()
    if not entry:
        raise AppError("INVITATION_INVALID", "邀请无效。", 400)
    Family.objects.select_for_update().get(pk=entry.family_id)
    invitation = Invitation.objects.select_for_update().filter(pk=entry.pk).first()
    if not invitation or invitation.used_at or invitation.expires_at <= timezone.now():
        raise AppError("INVITATION_INVALID", "邀请已使用或过期。", 400)
    if invitation.family.members.filter(user=user, active=True).exists():
        raise AppError("ALREADY_MEMBER", "你已在该家庭中。", 409)
    children = list(
        invitation.family.children.filter(pk__in=invitation.child_ids, deleted_at__isnull=True)
    )
    if len(children) != len(invitation.child_ids):
        raise AppError("INVITATION_INVALID", "邀请的档案已变更，请重新邀请。", 409)
    member, _ = FamilyMember.objects.update_or_create(
        family=invitation.family, user=user, defaults={"role": invitation.role, "active": True}
    )
    ChildAccessGrant.objects.filter(member=member).delete()
    for child in children:
        ChildAccessGrant.objects.create(member=member, child=child)
    invitation.used_at = timezone.now()
    invitation.save(update_fields=["used_at"])
    audit(user, "invitation_accepted", invitation, invitation.family)
    return invitation.family


@transaction.atomic
def revoke_member(user, member):
    family = family_for(user, member.family_id, owner=True)
    if member.user_id == family.owner_id:
        raise PermissionDenied()
    member.active = False
    member.save(update_fields=["active"])
    ChildAccessGrant.objects.filter(member=member).delete()
    AuthSession.objects.filter(user_id=member.user_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    audit(user, "member_revoked", member, family)


@transaction.atomic
def request_deletion(user, child=None):
    from apps.ocr.services import cancel_scope

    if child:
        child_for(user, child.pk, manage=True)
        cancel_scope(child_id=child.pk)
    else:
        for family_id in Family.objects.filter(owner=user).values_list("pk", flat=True):
            cancel_scope(family_id=family_id)
        cancel_scope(actor_id=user.pk)
    now = timezone.now()
    if child:
        child = child_for(user, child.pk, manage=True)
        child = get_object_or_404(
            ChildProfile.objects.select_for_update(), pk=child.pk, deleted_at__isnull=True
        )
        child.deleted_at = now
        child.save(update_fields=["deleted_at"])
        GuardianConsent.objects.filter(child=child, revoked_at__isnull=True).update(revoked_at=now)
        target_id, kind, family_id = str(child.pk), "child", child.family_id
    else:
        get_user_model().objects.select_for_update().get(pk=user.pk)
        list(Family.objects.select_for_update().filter(owner=user))
        if FamilyMember.objects.filter(family__owner=user, active=True).exclude(user=user).exists():
            raise AppError(
                "FAMILY_HAS_OTHER_MEMBERS", "请先处理自己家庭中的其他成员，再申请注销。", 409
            )
        user.is_active = False
        user.save(update_fields=["is_active"])
        AuthSession.objects.filter(user=user).update(revoked_at=now)
        FamilyMember.objects.filter(user=user).update(active=False)
        target_id, kind, family_id = str(user.pk), "account", None
    receipt = secrets.token_urlsafe(32)
    request = DeletionRequest.objects.create(
        actor_id=user.pk,
        target_id=target_id,
        target_type=kind,
        family_id=family_id,
        receipt_hash=digest(receipt),
    )
    audit(user, "deletion_requested", request)
    # A periodic database sweep recovers publication failures and process crashes.
    from .tasks import process_deletions

    transaction.on_commit(lambda: process_deletions.apply_async(), robust=True)
    return {"task_id": request.pk, "status": "queued", "deletion_receipt": receipt}


def process_pending_deletions():
    for identifier in DeletionRequest.objects.filter(status="queued").values_list("id", flat=True):
        with transaction.atomic():
            request = DeletionRequest.objects.select_for_update().get(pk=identifier)
            if request.status != "queued":
                continue
            if request.target_type == "child":
                ChildProfile.objects.filter(
                    pk=request.target_id, family_id=request.family_id, deleted_at__isnull=False
                ).delete()
            else:
                user = (
                    get_user_model().objects.filter(pk=request.target_id, is_active=False).first()
                )
                if user:
                    Family.objects.filter(owner=user).delete()
                    user.delete()
            request.status, request.completed_at = "succeeded", timezone.now()
            request.save(update_fields=["status", "completed_at"])
