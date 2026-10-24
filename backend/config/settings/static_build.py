"""Static asset collection only: no application URLs, database or runtime secrets."""

import secrets
from pathlib import Path

SECRET_KEY = secrets.token_urlsafe(64)
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
STATIC_URL = "/static/"
STATIC_ROOT = Path(__file__).resolve().parents[2] / "staticfiles"
ROOT_URLCONF = "config.static_urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
