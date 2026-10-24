import io
import json
import logging
import unittest
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import SimpleTestCase, TestCase
from redis import ConnectionError as RedisConnectionError

from apps.infrastructure.health import check_database, check_redis
from config.logging import SafeJSONFormatter
from config.runtime import load_runtime


def valid_env(environment="prod"):
    return {
        "APP_ENV": environment,
        "DJANGO_SECRET_KEY": "isolated-unit-only-" + "abcdefghijklmnopqrstuvwxyz0123456789",
        "DB_HOST": "db.example.invalid",
        "DB_NAME": "tiyoujie_prod",
        "DB_USER": "app",
        "DB_PASSWORD": "unit-db-only",
        "REDIS_URL": "rediss://cache.example.invalid:6379/0",
        "DJANGO_ALLOWED_HOSTS": "app.example.invalid",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.invalid",
        "PRIVATE_STORAGE_ROOT": "/private",
    }


class ConfigurationTests(SimpleTestCase):
    def test_valid_deployment_configuration(self):
        self.assertEqual(load_runtime("prod", valid_env()).environment, "prod")

    def test_required_configuration_is_fail_closed(self):
        for name in (
            "DJANGO_SECRET_KEY",
            "DB_HOST",
            "DB_NAME",
            "DB_USER",
            "DB_PASSWORD",
            "REDIS_URL",
            "DJANGO_ALLOWED_HOSTS",
            "PRIVATE_STORAGE_ROOT",
        ):
            with self.subTest(name=name):
                env = valid_env()
                env.pop(name)
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("prod", env)

    def test_secret_length_and_diversity(self):
        for secret in ("short", "x" * 60, "changeme-" * 10):
            with self.subTest(secret_length=len(secret)):
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("prod", {**valid_env(), "DJANGO_SECRET_KEY": secret})

    def test_module_and_environment_must_agree(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("dev", valid_env("prod"))

    def test_debug_and_dev_login_forbidden_in_deployment(self):
        for flag in ("DJANGO_DEBUG", "DEV_LOGIN_ENABLED"):
            with self.subTest(flag=flag):
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("prod", {**valid_env(), flag: "1"})

    def test_deployment_hosts_and_https_required(self):
        for change in (
            {"DJANGO_ALLOWED_HOSTS": "*"},
            {"DJANGO_CSRF_TRUSTED_ORIGINS": "http://app.example.invalid"},
            {"REDIS_URL": "redis://cache.example.invalid/0"},
        ):
            with self.subTest(fields=list(change)):
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("prod", {**valid_env(), **change})

    def test_test_config_cannot_target_external_database_or_queue(self):
        env = {
            **valid_env("test"),
            "DB_HOST": "postgres-test",
            "DB_NAME": "tiyoujie_test",
            "DB_USER": "tiyoujie_test",
            "REDIS_URL": "redis://redis-test:6379/0",
            "ISOLATED_TEST_RUN": "1",
        }
        self.assertEqual(load_runtime("test", env).database["HOST"], "postgres-test")
        for change in (
            {"DB_HOST": "production.invalid"},
            {"DB_NAME": "customer_data"},
            {"DB_USER": "postgres"},
            {"REDIS_URL": "redis://redis:6379/0"},
            {"ISOLATED_TEST_RUN": "0"},
        ):
            with self.subTest(fields=list(change)):
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("test", {**env, **change})

    def test_non_test_settings_reject_test_database(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", {**valid_env(), "DB_NAME": "tiyoujie_test"})

    def test_ai_and_dev_login_are_disabled(self):
        self.assertFalse(settings.PLATFORM_AI_ENABLED)
        self.assertFalse(settings.DEV_LOGIN_ENABLED)
        self.assertFalse(settings.CELERY_TASK_ALWAYS_EAGER)


class LoggingTests(SimpleTestCase):
    def test_sensitive_messages_arguments_and_traceback_are_discarded(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SafeJSONFormatter())
        logger = logging.getLogger("isolated-log-test")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        try:
            raise ValueError("sensitive-exception-body")
        except ValueError:
            logger.exception(
                "Authorization %s",
                "sensitive-header-body",
                extra={"request_id": "trace", "event": "api_failure"},
            )
        output = stream.getvalue()
        self.assertNotIn("sensitive", output)
        self.assertEqual(json.loads(output)["request_id"], "trace")


class HealthTests(TestCase):
    def test_live_and_request_metadata(self):
        response = self.client.get("/api/v1/health/live/?token=do-not-log")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai"], "disabled")
        self.assertEqual(len(response["X-Request-ID"]), 32)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_ready_uses_real_migrated_postgres_and_redis(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.settings_dict["HOST"], "postgres-test")
        check_database()
        check_redis()
        response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checks"], {"database": "ok", "queue": "ok"})

    def test_database_failure_returns_503_without_details(self):
        with patch(
            "apps.infrastructure.health.check_database", side_effect=RuntimeError("sensitive-dsn")
        ):
            response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["database"], "unavailable")
        self.assertNotContains(response, "sensitive", status_code=503)

    def test_queue_failure_returns_503_without_details(self):
        with patch(
            "apps.infrastructure.health.check_redis",
            side_effect=RedisConnectionError("sensitive-queue-password"),
        ):
            response = self.client.get("/api/v1/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["queue"], "unavailable")
        self.assertNotContains(response, "sensitive", status_code=503)

    def test_unmigrated_schema_is_not_ready(self):
        with patch("apps.infrastructure.health.connection.cursor") as cursor:
            cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
            with self.assertRaises(RuntimeError):
                check_database()

    def test_missing_scope_guard_migration_is_not_ready(self):
        with patch("apps.infrastructure.health.connection.cursor") as cursor:
            handle = cursor.return_value.__enter__.return_value
            handle.fetchone.return_value = (True,)
            handle.fetchall.return_value = [("problems", "0001_initial")]
            with self.assertRaises(RuntimeError):
                check_database()

    def test_business_routes_require_identity_and_admin_requires_login(self):
        self.assertEqual(self.client.get("/api/v1/problems/").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/provider-credentials/").status_code, 401)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_health_rejects_mutations(self):
        self.assertEqual(self.client.post("/api/v1/health/live/").status_code, 405)


if __name__ == "__main__":
    unittest.main()
