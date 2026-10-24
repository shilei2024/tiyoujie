from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.access import child_for, children_for
from apps.accounts.models import Family, GuardianConsent
from apps.accounts.services import audit
from config.errors import AppError

from .images import normalize, transform
from .models import Asset, Problem, ProblemAsset, ProblemTextVersion, StoredObject
from .storage import new_key, storage


def problem_for(user, identifier, manage=False):
    problem = get_object_or_404(
        Problem.objects.select_related("child", "current_text"),
        pk=identifier,
        deleted_at__isnull=True,
        child__deleted_at__isnull=True,
    )
    child_for(user, problem.child_id, manage=manage)
    return problem


def asset_for(user, identifier, manage=False):
    asset = get_object_or_404(
        Asset.objects.select_related("object", "child"),
        pk=identifier,
        object__state="live",
        child__deleted_at__isnull=True,
    )
    child_for(user, asset.child_id, manage=manage)
    if not asset.problem_links.filter(problem__deleted_at__isnull=True).exists():
        raise AppError("NOT_FOUND", "图片不可访问。", 404)
    return asset


def require_profile_consent(child):
    if not GuardianConsent.objects.filter(
        child=child,
        scope="profile",
        revoked_at__isnull=True,
        notice_version=settings.GUARDIAN_NOTICE_VERSION,
    ).exists():
        raise AppError("CONSENT_REQUIRED", "请先由监护人授权管理学习档案。", 403)


def check_revision(problem, expected):
    if problem.revision != expected:
        raise AppError("VERSION_CONFLICT", "记录已更新，请重新载入后再保存。", 409)


@transaction.atomic
def create_problem(user, data):
    child = child_for(user, data.pop("child_id"), manage=True)
    Family.objects.select_for_update().get(pk=child.family_id)
    require_profile_consent(child)
    if (
        Problem.objects.filter(child__family_id=child.family_id, deleted_at__isnull=True).count()
        >= settings.FAMILY_PROBLEM_LIMIT
    ):
        raise AppError("PROBLEM_LIMIT", "已达到本家庭的错题数量限额。", 403)
    result = Problem.objects.create(child=child, created_by=user, **data)
    audit(user, "problem_created", result, child.family)
    return result


@transaction.atomic
def update_problem(user, identifier, data):
    problem = problem_for(user, identifier, manage=True)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    problem = get_object_or_404(
        Problem.objects.select_for_update(), pk=identifier, deleted_at__isnull=True
    )
    require_profile_consent(problem.child)
    check_revision(problem, data.pop("expected_revision"))
    for key, value in data.items():
        setattr(problem, key, value)
    problem.revision += 1
    problem.save(update_fields=[*data, "revision"])
    audit(user, "problem_updated", problem, problem.child.family)
    return problem


@transaction.atomic
def save_text(user, identifier, data):
    problem = problem_for(user, identifier, manage=True)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    problem = get_object_or_404(
        Problem.objects.select_for_update(), pk=identifier, deleted_at__isnull=True
    )
    require_profile_consent(problem.child)
    check_revision(problem, data["expected_revision"])
    if not data["confirmed"]:
        raise AppError("CONFIRM_REQUIRED", "请先核对题干，再确认保存。", 400)
    parent_id = data.get("parent_id") or problem.current_text_id
    parent = (
        get_object_or_404(ProblemTextVersion, pk=parent_id, problem=problem) if parent_id else None
    )
    version = append_text(
        problem,
        origin="manual",
        text=data["text"],
        answer=data["answer"],
        confirmed=True,
        parent=parent,
        created_by=user,
    )
    problem.current_text = version
    problem.revision += 1
    problem.save(update_fields=["current_text", "revision"])
    audit(user, "problem_text_confirmed", version, problem.child.family)
    return problem


def append_text(problem, **values):
    number = (problem.text_versions.aggregate(value=Max("number"))["value"] or 0) + 1
    return ProblemTextVersion.objects.create(problem=problem, number=number, **values)


def reserve_object(user, child_id, byte_size):
    with transaction.atomic():
        child = child_for(user, child_id, manage=True)
        Family.objects.select_for_update().get(pk=child.family_id)
        require_profile_consent(child)
        used = (
            StoredObject.objects.filter(family_id=child.family_id).aggregate(size=Sum("byte_size"))[
                "size"
            ]
            or 0
        )
        if used + byte_size > settings.FAMILY_STORAGE_BYTES:
            raise AppError(
                "STORAGE_QUOTA_EXHAUSTED", "家庭图片存储空间不足，请先清理不需要的资料。", 403
            )
        return StoredObject.objects.create(
            family_id=child.family_id, child_id=child.pk, object_key=new_key(), byte_size=byte_size
        )


def install_assets(
    user, problem_id, processed, *, parent=None, split=False, expected=None, transforms=None
):
    original = problem_for(user, problem_id, manage=True)
    records = []
    try:
        for content, _, _, _ in processed:
            record = reserve_object(user, original.child_id, len(content))
            records.append(record)
            storage().put(record.object_key, content)
        with transaction.atomic():
            Family.objects.select_for_update().get(pk=original.child.family_id)
            original = problem_for(user, problem_id, manage=True)
            original = get_object_or_404(
                Problem.objects.select_for_update(), pk=original.pk, deleted_at__isnull=True
            )
            require_profile_consent(original.child)
            if expected is not None:
                check_revision(original, expected)
            if parent:
                parent = asset_for(user, parent.pk, manage=True)
                get_object_or_404(ProblemAsset, problem=original, asset=parent)
            if (
                not split
                and original.asset_links.count() + len(records) > settings.PROBLEM_ASSET_LIMIT
            ):
                raise AppError("ASSET_LIMIT", "单题图片数量已达到限额。", 403)
            results = []
            for index, (record, (_, width, height, sha)) in enumerate(
                zip(records, processed, strict=True)
            ):
                target = (
                    create_problem(user, {"child_id": original.child_id, "source": original.source})
                    if split
                    else original
                )
                asset = Asset.objects.create(
                    child_id=original.child_id,
                    object=record,
                    width=width,
                    height=height,
                    sha256=sha,
                    parent=parent,
                    transform=transforms[index] if transforms else {},
                )
                ProblemAsset.objects.create(problem=target, asset=asset)
                record.state = "live"
                record.save(update_fields=["state"])
                results.append((target, asset))
            original.revision += 1
            original.save(update_fields=["revision"])
            audit(user, "problem_images_added", original, original.child.family)
            return results
    except Exception:
        StoredObject.objects.filter(pk__in=[r.pk for r in records], state="staged").update(
            state="purge_pending"
        )
        raise


def upload_asset(user, problem_id, upload):
    problem_for(user, problem_id, manage=True)
    return install_assets(user, problem_id, [normalize(upload)])[0][1]


def transform_asset(user, identifier, data):
    parent = asset_for(user, identifier, manage=True)
    problem = problem_for(user, data["problem_id"], manage=True)
    get_object_or_404(ProblemAsset, problem=problem, asset=parent)
    content = storage().read(parent.object.object_key)
    processed = [transform(content, region) for region in data["regions"]]
    return install_assets(
        user,
        problem.pk,
        processed,
        parent=parent,
        split=data["split"],
        expected=data["expected_revision"],
        transforms=data["regions"],
    )


@transaction.atomic
def attach_asset(user, problem_id, asset_id, expected):
    problem = problem_for(user, problem_id, manage=True)
    asset = asset_for(user, asset_id, manage=True)
    if asset.child_id != problem.child_id:
        raise AppError("ASSET_SCOPE_INVALID", "图片和题目必须属于同一孩子。", 400)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    problem = Problem.objects.select_for_update().get(pk=problem.pk)
    check_revision(problem, expected)
    require_profile_consent(problem.child)
    if problem.asset_links.count() >= settings.PROBLEM_ASSET_LIMIT:
        raise AppError("ASSET_LIMIT", "单题图片数量已达到限额。", 403)
    ProblemAsset.objects.get_or_create(problem=problem, asset=asset)
    problem.revision += 1
    problem.save(update_fields=["revision"])
    return problem


def remove_unreferenced_assets():
    Asset.objects.filter(problem_links__isnull=True).delete()


@transaction.atomic
def detach_asset(user, problem_id, asset_id, expected):
    from apps.ocr.services import cancel_scope

    problem = problem_for(user, problem_id, manage=True)
    asset = asset_for(user, asset_id, manage=True)
    get_object_or_404(ProblemAsset, problem=problem, asset=asset)
    cancel_scope(problem_id=problem.pk, asset_id=asset.pk)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    problem = Problem.objects.select_for_update().get(pk=problem.pk)
    check_revision(problem, expected)
    get_object_or_404(ProblemAsset, problem=problem, asset=asset).delete()
    problem.revision += 1
    problem.save(update_fields=["revision"])
    if not asset.problem_links.exists():
        asset.delete()
    audit(user, "problem_image_removed", problem, problem.child.family)
    return problem


@transaction.atomic
def delete_problem(user, identifier):
    from apps.ocr.services import cancel_scope

    problem = problem_for(user, identifier, manage=True)
    cancel_scope(problem_id=problem.pk)
    Family.objects.select_for_update().get(pk=problem.child.family_id)
    problem = Problem.objects.select_for_update().get(pk=problem.pk)
    problem.deleted_at = timezone.now()
    problem.save(update_fields=["deleted_at"])
    audit(user, "problem_deleted", problem, problem.child.family)
    problem.delete()
    remove_unreferenced_assets()


def cleanup_objects(now=None):
    now = now or timezone.now()
    candidates = StoredObject.objects.filter(state="purge_pending") | StoredObject.objects.filter(
        state="staged", created_at__lt=now - timedelta(hours=1)
    )
    for identifier in candidates.values_list("pk", flat=True):
        with transaction.atomic():
            record = StoredObject.objects.select_for_update().filter(pk=identifier).first()
            if record and not Asset.objects.filter(object=record).exists():
                storage().delete(record.object_key)
                record.delete()
    # Covers a process crash combined with an outer transaction rollback.
    for key in storage().old_keys((now - timedelta(hours=1)).timestamp()):
        if not StoredObject.objects.filter(object_key=key).exists():
            storage().delete(key)


def list_problems(user, family_id):
    return Problem.objects.filter(child__in=children_for(user, family_id), deleted_at__isnull=True)
