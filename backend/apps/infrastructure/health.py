from django.conf import settings
from django.db import connection
from redis import Redis


def check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('django_migrations') IS NOT NULL")
        if not cursor.fetchone()[0]:
            raise RuntimeError("Schema is not initialized")
        cursor.execute("SELECT app, name FROM django_migrations")
        required = {
            ("sessions", "0001_initial"),
            ("accounts", "0002_guardianconsent_one_active_consent_per_scope"),
            ("credentials", "0001_initial"),
            ("entitlements", "0001_initial"),
            ("problems", "0003_text_history_guard"),
            ("metering", "0003_budgetpolicy_alert_at_percent_budgetwindow_alerted"),
            ("ocr", "0004_ocrmodel_analysis_quota_units_and_more"),
            ("ai_tutor", "0002_scope_guards"),
            ("question_bank", "0002_review_guards"),
        }
        if not required.issubset(set(cursor.fetchall())):
            raise RuntimeError("Required migrations are missing")


def check_redis():
    with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2) as client:
        if not client.ping():
            raise RuntimeError("Queue is unavailable")


def readiness():
    checks = {}
    for name, check in (("database", check_database), ("queue", check_redis)):
        try:
            check()
            checks[name] = "ok"
        except Exception:
            checks[name] = "unavailable"
    return checks
