"""Validate environment before configuring Django or opening any connection."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class Runtime:
    environment: str
    secret_key: str
    hosts: list[str]
    csrf_origins: list[str]
    database: dict
    redis_url: str


def load_runtime(expected: str, env=None) -> Runtime:
    values = os.environ if env is None else env
    if expected not in {"dev", "test", "staging", "prod"}:
        raise ImproperlyConfigured("Unsupported application environment")
    if values.get("APP_ENV") != expected:
        raise ImproperlyConfigured("APP_ENV and settings module must agree")

    def required(name):
        value = values.get(name, "").strip()
        if not value or value.lower().startswith(("changeme", "example", "replace")):
            raise ImproperlyConfigured(f"Missing or invalid configuration: {name}")
        return value

    secret = required("DJANGO_SECRET_KEY")
    if len(secret) < 50 or len(set(secret)) < 8:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong independent secret")
    host = required("DB_HOST")
    name = required("DB_NAME")
    user = required("DB_USER")
    password = required("DB_PASSWORD")
    redis_url = required("REDIS_URL")
    redis_parts = urlsplit(redis_url)
    if redis_parts.scheme not in {"redis", "rediss"} or not redis_parts.hostname:
        raise ImproperlyConfigured("REDIS_URL must identify a Redis service")
    hosts = [x.strip() for x in required("DJANGO_ALLOWED_HOSTS").split(",") if x.strip()]
    origins = [x.strip() for x in values.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x]
    if expected == "test":
        if (host, name, user, redis_parts.hostname) != (
            "postgres-test",
            "tiyoujie_test",
            "tiyoujie_test",
            "redis-test",
        ) or values.get("ISOLATED_TEST_RUN") != "1":
            raise ImproperlyConfigured("Tests require the dedicated isolated Compose services")
    elif "test" in name.lower() or host == "postgres-test":
        raise ImproperlyConfigured("Non-test configuration cannot use the test database")
    if expected in {"staging", "prod"}:
        if values.get("DJANGO_DEBUG", "0") != "0":
            raise ImproperlyConfigured("Debug is forbidden outside local development")
        if not hosts or any(x in {"*", "localhost", "127.0.0.1"} for x in hosts):
            raise ImproperlyConfigured("Explicit deployment hosts are required")
        if not origins or any(not x.startswith("https://") for x in origins):
            raise ImproperlyConfigured("Deployment CSRF origins must use HTTPS")
        if not values.get("PRIVATE_STORAGE_ROOT", "").startswith("/"):
            raise ImproperlyConfigured("A private absolute storage path is required")
        if redis_parts.scheme != "rediss" and not redis_parts.password:
            raise ImproperlyConfigured("Deployment Redis must use authentication or TLS")
        if values.get("DEV_LOGIN_ENABLED", "0") != "0":
            raise ImproperlyConfigured("Development login is forbidden in deployment")
    return Runtime(
        expected,
        secret,
        hosts,
        origins,
        {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": host,
            "PORT": "5432",
            "NAME": name,
            "USER": user,
            "PASSWORD": password,
            "CONN_MAX_AGE": 0,
            "OPTIONS": {"connect_timeout": 3},
            "TEST": {"NAME": "test_tiyoujie_isolated"} if expected == "test" else {},
        },
        redis_url,
    )
