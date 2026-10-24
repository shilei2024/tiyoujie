import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.access import family_for, member_for
from apps.accounts.models import AuditEvent
from apps.accounts.services import audit
from config.errors import AppError

from .models import UserProviderCredential


def keyring():
    try:
        data = json.loads(settings.CREDENTIAL_KEYS_JSON)
        keys = {name: base64.b64decode(value, validate=True) for name, value in data.items()}
        if not keys or any(
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", name) or len(value) != 32
            for name, value in keys.items()
        ):
            raise ValueError()
        if settings.CREDENTIAL_ACTIVE_KEY_VERSION not in keys:
            raise ValueError()
        return keys
    except (ValueError, TypeError, AttributeError):
        raise AppError("CREDENTIAL_STORAGE_UNAVAILABLE", "凭证加密配置不可用。", 503) from None


def aad(credential):
    return (
        f"{credential.pk}:{credential.family_id}:"
        f"{credential.provider}:{credential.credential_version}"
    ).encode()


def encrypt(credential, plaintext, version=None):
    keys = keyring()
    version = version or settings.CREDENTIAL_ACTIVE_KEY_VERSION
    if version not in keys:
        raise AppError("CREDENTIAL_STORAGE_UNAVAILABLE", "加密版本不可用。", 503)
    credential.nonce = os.urandom(12)
    credential.ciphertext = AESGCM(keys[version]).encrypt(
        credential.nonce, plaintext.encode(), aad(credential)
    )
    credential.key_version = version


def decrypt(credential):
    try:
        return (
            AESGCM(keyring()[credential.key_version])
            .decrypt(bytes(credential.nonce), bytes(credential.ciphertext), aad(credential))
            .decode()
        )
    except (InvalidTag, KeyError, UnicodeDecodeError):
        raise AppError("CREDENTIAL_UNAVAILABLE", "凭证无法使用，请重新配置。", 503) from None


def credential_for(user, identifier):
    credential = get_object_or_404(
        UserProviderCredential, pk=identifier, owner=user, deleted_at__isnull=True
    )
    member = member_for(user, credential.family_id)
    if member.role != "guardian":
        raise AppError("FORBIDDEN", "没有凭证管理权限。", 403)
    return credential


@transaction.atomic
def save_credential(user, family_id, provider, plaintext):
    family = family_for(user, family_id)
    if member_for(user, family_id).role != "guardian":
        raise AppError("FORBIDDEN", "学生不能配置服务凭证。", 403)
    credential = UserProviderCredential(
        family=family, owner=user, provider=provider, suffix=plaintext[-4:]
    )
    encrypt(credential, plaintext)
    credential.save()
    audit(user, "credential_created", credential, family)
    return credential


@transaction.atomic
def replace_credential(user, identifier, plaintext):
    credential_for(user, identifier)
    credential = get_object_or_404(
        UserProviderCredential.objects.select_for_update(),
        pk=identifier,
        owner=user,
        deleted_at__isnull=True,
    )
    credential.credential_version += 1
    credential.suffix = plaintext[-4:]
    credential.validation_status = "not_verified"
    encrypt(credential, plaintext)
    credential.save()
    audit(user, "credential_replaced", credential, credential.family)
    return credential


@transaction.atomic
def change_credential(user, identifier, enabled=None, delete=False):
    credential_for(user, identifier)
    credential = get_object_or_404(
        UserProviderCredential.objects.select_for_update(),
        pk=identifier,
        owner=user,
        deleted_at__isnull=True,
    )
    credential.credential_version += 1
    credential.enabled = False if delete else enabled
    credential.validation_status = "not_verified"
    if delete:
        credential.deleted_at = timezone.now()
        credential.ciphertext, credential.nonce, credential.suffix = b"", b"", ""
    else:
        # Version is authenticated; re-encrypt when versioning enabled/disabled state.
        previous_version = credential.credential_version - 1
        credential.credential_version = previous_version
        plaintext = decrypt(credential)
        credential.credential_version += 1
        encrypt(credential, plaintext)
    credential.save()
    audit(
        user,
        "credential_deleted" if delete else "credential_toggled",
        credential,
        credential.family,
    )
    return credential


def credential_for_use(user, identifier, expected_version):
    credential = credential_for(user, identifier)
    if not credential.enabled or credential.credential_version != expected_version:
        raise AppError("CREDENTIAL_REVOKED", "凭证已更改或停用，请重新选择。", 409)
    return decrypt(credential)


@transaction.atomic
def rotate_master_key(version):
    count = 0
    for credential in (
        UserProviderCredential.objects.select_for_update()
        .filter(deleted_at__isnull=True)
        .order_by("id")
    ):
        plaintext = decrypt(credential)
        encrypt(credential, plaintext, version)
        credential.save()
        count += 1
    AuditEvent.objects.create(
        action="credential_master_rotated",
        object_id=version,
        reason="Server-side master key rotation",
    )
    return count
