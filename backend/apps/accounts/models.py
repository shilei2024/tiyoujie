import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Entity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class AuthIdentity(Entity):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=16)
    app_id = models.CharField(max_length=64)
    subject = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "app_id", "subject"], name="identity_unique"
            )
        ]


class AuthSession(Entity):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    access_hash = models.CharField(max_length=64, unique=True)
    access_expires_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    is_test_login = models.BooleanField(default=False)


class RefreshToken(Entity):
    session = models.ForeignKey(AuthSession, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True)


class Family(Entity):
    name = models.CharField(max_length=40)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class FamilyMember(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=[("guardian", "监护人"), ("student", "学生")])
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["family", "user"], name="member_unique")]


class ChildProfile(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="children")
    nickname = models.CharField(max_length=32)
    grade = models.PositiveSmallIntegerField(null=True, blank=True)
    semester = models.CharField(max_length=12, blank=True)
    textbook = models.CharField(max_length=40, blank=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(grade__isnull=True) | Q(grade__gte=1, grade__lte=12), name="grade_range"
            )
        ]


class ChildAccessGrant(Entity):
    member = models.ForeignKey(FamilyMember, on_delete=models.CASCADE)
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "child"], name="child_access_unique")
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.member.family_id != self.child.family_id:
            raise ValidationError("家庭与孩子归属不一致")


class GuardianConsent(Entity):
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE)
    guardian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notice_version = models.CharField(max_length=32)
    scope = models.CharField(
        max_length=32,
        choices=[("profile", "档案管理"), ("deepseek", "DeepSeek 外发"), ("kimi", "Kimi 外发")],
    )
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["child", "scope"],
                condition=Q(revoked_at__isnull=True),
                name="one_active_consent_per_scope",
            )
        ]


class Invitation(Entity):
    family = models.ForeignKey(Family, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=16)
    child_ids = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class AuditEvent(Entity):
    actor_id = models.PositiveIntegerField(null=True)
    family_id = models.UUIDField(null=True)
    action = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    reason = models.CharField(max_length=200, blank=True)


class DeletionRequest(Entity):
    actor_id = models.PositiveIntegerField()
    family_id = models.UUIDField(null=True)
    target_id = models.CharField(max_length=64)
    target_type = models.CharField(max_length=16)
    receipt_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="queued")
    completed_at = models.DateTimeField(null=True)
