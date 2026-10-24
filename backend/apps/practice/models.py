import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.models import ChildProfile, Entity


class Worksheet(Entity):
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE, related_name="worksheets")
    title = models.CharField(max_length=40)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    revision = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=["child", "deleted_at", "created_at", "id"])]


class WorksheetItem(Entity):
    worksheet = models.ForeignKey(Worksheet, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveSmallIntegerField()
    origin = models.CharField(
        max_length=12, choices=[("problem", "错题"), ("bank", "题库"), ("variant", "变式草稿")]
    )
    problem = models.ForeignKey(
        "problems.Problem", null=True, on_delete=models.CASCADE, related_name="worksheet_items"
    )
    bank_item_id = models.UUIDField(null=True)
    bank_revision = models.PositiveIntegerField(null=True)
    text = models.TextField(max_length=4000)
    answer = models.TextField(max_length=2000, blank=True)
    explanation = models.TextField(max_length=4000, blank=True)
    knowledge_points = models.JSONField(default=list, blank=True)
    math_spec = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["worksheet", "position"], name="worksheet_position_once"
            ),
            models.CheckConstraint(
                condition=(
                    Q(origin="bank", problem__isnull=True)
                    & Q(bank_item_id__isnull=False, bank_revision__isnull=False)
                )
                | (
                    Q(origin__in=["problem", "variant"], problem__isnull=False)
                    & Q(bank_item_id__isnull=True, bank_revision__isnull=True)
                ),
                name="worksheet_item_origin_binding",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="worksheet_item_position_positive"
            ),
        ]


class Attempt(Entity):
    item = models.ForeignKey(WorksheetItem, on_delete=models.CASCADE, related_name="attempts")
    number = models.PositiveSmallIntegerField()
    answer = models.TextField(max_length=2000, blank=True)
    self_grade = models.CharField(
        max_length=8, choices=[("correct", "答对"), ("wrong", "答错"), ("unsure", "不确定")]
    )
    is_correct = models.BooleanField(null=True)
    graded_by = models.CharField(
        max_length=12, choices=[("auto", "结构核验"), ("self", "自评")], default="self"
    )
    duration_seconds = models.PositiveIntegerField(null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "number"], name="attempt_number_once"),
            models.CheckConstraint(condition=Q(number__gte=1), name="attempt_number_positive"),
        ]


class ReviewSchedule(Entity):
    child = models.ForeignKey(
        ChildProfile, on_delete=models.CASCADE, related_name="review_schedules"
    )
    problem = models.ForeignKey(
        "problems.Problem", on_delete=models.CASCADE, related_name="review_schedules"
    )
    due_on = models.DateField()
    level = models.PositiveSmallIntegerField(default=0)
    interval_days = models.PositiveSmallIntegerField(default=1)
    streak = models.PositiveSmallIntegerField(default=0)
    lapses = models.PositiveSmallIntegerField(default=0)
    stage = models.CharField(
        max_length=12,
        choices=[
            ("new", "待开始"),
            ("learning", "学习中"),
            ("review", "复习中"),
            ("mastered", "已掌握"),
        ],
        default="new",
    )
    last_graded_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["child", "problem"], name="review_schedule_once"),
            models.CheckConstraint(
                condition=Q(level__lte=6, interval_days__gte=1), name="review_schedule_range"
            ),
        ]
        indexes = [models.Index(fields=["child", "due_on"])]


class ReviewEvent(Entity):
    """Append-only record of one spaced-review decision."""

    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE, related_name="review_events")
    problem = models.ForeignKey("problems.Problem", on_delete=models.CASCADE)
    grade = models.CharField(max_length=8)
    level_before = models.PositiveSmallIntegerField()
    level_after = models.PositiveSmallIntegerField()
    interval_after = models.PositiveSmallIntegerField()
    due_on = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(level_before__lte=6, level_after__lte=6), name="review_event_range"
            )
        ]


class ExportTicket(Entity):
    """Short-lived, revocable permission to render one private export."""

    kind = models.CharField(max_length=16, choices=[("worksheet", "题单"), ("summary", "学习概览")])
    child = models.ForeignKey(ChildProfile, on_delete=models.CASCADE, related_name="export_tickets")
    worksheet = models.ForeignKey(Worksheet, null=True, on_delete=models.CASCADE)
    nonce = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="worksheet", worksheet__isnull=False)
                    | Q(kind="summary", worksheet__isnull=True)
                ),
                name="export_ticket_target",
            )
        ]
