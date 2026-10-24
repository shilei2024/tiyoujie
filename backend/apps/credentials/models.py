from django.conf import settings
from django.db import models

from apps.accounts.models import Entity, Family


class UserProviderCredential(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=16, choices=[("deepseek", "DeepSeek"), ("kimi", "Kimi")])
    ciphertext = models.BinaryField()
    nonce = models.BinaryField()
    key_version = models.CharField(max_length=32)
    credential_version = models.PositiveIntegerField(default=1)
    suffix = models.CharField(max_length=4)
    enabled = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True)
    validation_status = models.CharField(max_length=24, default="not_verified")
    updated_at = models.DateTimeField(auto_now=True)
