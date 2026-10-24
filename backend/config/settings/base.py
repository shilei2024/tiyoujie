import os
from pathlib import Path

from config.runtime import load_runtime

BASE_DIR = Path(__file__).resolve().parents[2]


def configure(environment):
    runtime = load_runtime(environment)
    deployed = environment in {"staging", "prod"}
    return {
        "APP_ENV": environment,
        "AI_ANALYSIS_ENABLED": os.environ.get("AI_ANALYSIS_ENABLED") == "1",
        "SECRET_KEY": runtime.secret_key,
        "DEBUG": False,
        "ALLOWED_HOSTS": runtime.hosts,
        "CSRF_TRUSTED_ORIGINS": runtime.csrf_origins,
        "INSTALLED_APPS": [
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "django.contrib.admin",
            "rest_framework",
            "apps.infrastructure",
            "apps.accounts",
            "apps.credentials",
            "apps.entitlements",
            "apps.problems.apps.ProblemsConfig",
            "apps.metering",
            "apps.ocr",
            "apps.ai_tutor",
            "apps.question_bank",
            "apps.practice",
        ],
        "MIDDLEWARE": [
            "django.middleware.security.SecurityMiddleware",
            "whitenoise.middleware.WhiteNoiseMiddleware",
            "config.logging.RequestLogMiddleware",
            "apps.problems.middleware.RequestSizeMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            # 放在认证之后：限流要能识别已登录用户，且后台登录需要独立更紧的阈值。
            "apps.accounts.middleware.AdminLoginThrottle",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        "ROOT_URLCONF": "config.urls",
        "WSGI_APPLICATION": "config.wsgi.application",
        "DATABASES": {"default": runtime.database},
        "REST_FRAMEWORK": {
            "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.security.BearerAuthentication"],
            "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "EXCEPTION_HANDLER": "config.errors.exception_handler",
        },
        "LANGUAGE_CODE": "zh-hans",
        "TIME_ZONE": "UTC",
        "USE_TZ": True,
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "STATIC_URL": "/static/",
        "STATIC_ROOT": BASE_DIR / "staticfiles",
        "MEDIA_ROOT": os.environ.get("PRIVATE_STORAGE_ROOT", "/app/private"),
        "REDIS_URL": runtime.redis_url,
        "PLATFORM_AI_ENABLED": os.environ.get("PLATFORM_AI_ENABLED", "0") == "1",
        "OCR_OUTBOUND_ENABLED": os.environ.get("OCR_OUTBOUND_ENABLED", "0") == "1",
        "PLATFORM_OCR_CONFIGURED_PROVIDERS": set(
            filter(None, os.environ.get("PLATFORM_OCR_CONFIGURED_PROVIDERS", "").split(","))
        ),
        "PLATFORM_OCR_KEYS": {
            "deepseek": os.environ.get("PLATFORM_OCR_KEY_DEEPSEEK", ""),
            "kimi": os.environ.get("PLATFORM_OCR_KEY_KIMI", ""),
        },
        "IMAGE_MAX_BYTES": 8388608,
        "IMAGE_MAX_PIXELS": 12000000,
        "IMAGE_MAX_SIDE": 8192,
        "FAMILY_STORAGE_BYTES": 104857600,
        "FAMILY_PROBLEM_LIMIT": 1000,
        "PROBLEM_ASSET_LIMIT": 8,
        "FILE_UPLOAD_MAX_MEMORY_SIZE": 262144,
        "FILE_UPLOAD_HANDLERS": [
            "apps.problems.middleware.BoundedUpload",
            "django.core.files.uploadhandler.MemoryFileUploadHandler",
            "django.core.files.uploadhandler.TemporaryFileUploadHandler",
        ],
        "DATA_UPLOAD_MAX_NUMBER_FILES": 1,
        "DATA_UPLOAD_MAX_NUMBER_FIELDS": 20,
        "DEV_LOGIN_ENABLED": environment in {"dev", "test"}
        and os.environ.get("DEV_LOGIN_ENABLED", "0") == "1",
        "WECHAT_APP_ID": os.environ.get("WECHAT_APP_ID", ""),
        "WECHAT_APP_SECRET": os.environ.get("WECHAT_APP_SECRET", ""),
        "CREDENTIAL_KEYS_JSON": os.environ.get("CREDENTIAL_KEYS_JSON", ""),
        "CREDENTIAL_ACTIVE_KEY_VERSION": os.environ.get("CREDENTIAL_ACTIVE_KEY_VERSION", ""),
        "GUARDIAN_NOTICE_VERSION": "2026-10-v1",
        "ACCESS_TOKEN_MINUTES": 15,
        "REFRESH_TOKEN_DAYS": 14,
        "AUTH_RATE_LIMIT_COUNT": 20,
        # 后台登录页挂在公网域名上，阈值必须比业务接口紧；Django admin 自身没有防爆破。
        "ADMIN_LOGIN_LIMIT_COUNT": 10,
        "AUTH_THROTTLE_NAMESPACE": environment,
        "PRACTICE_TIME_ZONE": "Asia/Shanghai",
        "DATA_UPLOAD_MAX_MEMORY_SIZE": 65536,
        "TEMPLATES": [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "DIRS": [BASE_DIR / "templates"],
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        "CELERY_BEAT_SCHEDULE": {
            "entitlements": {
                "task": "apps.entitlements.tasks.reconcile_entitlements",
                "schedule": 60.0,
            },
            "deletions": {"task": "apps.accounts.tasks.process_deletions", "schedule": 60.0},
            "private_objects": {
                "task": "apps.problems.tasks.cleanup_private_objects",
                "schedule": 60.0,
            },
            "ocr_outbox_recovery": {"task": "apps.ocr.tasks.recover_ocr", "schedule": 60.0},
            "export_tickets": {
                "task": "apps.practice.tasks.cleanup_export_tickets",
                "schedule": 3600.0,
            },
        },
        "CELERY_BROKER_URL": runtime.redis_url,
        "CELERY_RESULT_BACKEND": runtime.redis_url,
        "CELERY_TASK_SERIALIZER": "json",
        "CELERY_RESULT_SERIALIZER": "json",
        "CELERY_ACCEPT_CONTENT": ["json"],
        "CELERY_TASK_ALWAYS_EAGER": False,
        "CELERY_TASK_DEFAULT_QUEUE": f"tiyoujie-{environment}",
        "CELERY_RESULT_EXPIRES": 300,
        "CELERY_TASK_TIME_LIMIT": 30,
        "CELERY_TASK_SOFT_TIME_LIMIT": 20,
        "CELERY_WORKER_HIJACK_ROOT_LOGGER": False,
        "CELERY_WORKER_SEND_TASK_EVENTS": False,
        "CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP": True,
        "SESSION_COOKIE_SECURE": deployed,
        "CSRF_COOKIE_SECURE": deployed,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SECURE_SSL_REDIRECT": deployed,
        # TLS 由前置代理（Caddy / nginx）终结时，WSGI 层看到的协议是 http。
        # 不信任该头会导致 SECURE_SSL_REDIRECT 把每个请求再跳一次，形成重定向死循环。
        # 因此只在部署环境启用，且应用端口必须只绑定回环地址，避免外部伪造该头。
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https") if deployed else None,
        # 仅部署在代理之后时信任 X-Forwarded-For（限流按真实客户端 IP 计）。
        "TRUST_FORWARDED_FOR": deployed,
        "SECURE_HSTS_SECONDS": 31536000 if deployed else 0,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": deployed,
        "SECURE_HSTS_PRELOAD": deployed,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "same-origin",
        "X_FRAME_OPTIONS": "DENY",
        "LOGGING": {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"safe": {"()": "config.logging.SafeJSONFormatter"}},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "safe"}},
            "root": {"handlers": ["console"], "level": "INFO"},
            "loggers": {
                "django.server": {"handlers": ["console"], "propagate": False},
                "django.request": {"handlers": ["console"], "propagate": False},
                "celery": {"handlers": ["console"], "propagate": False},
            },
        },
    }
