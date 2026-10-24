"""部署面配置回归测试：代理协议头、秘密强度与部署环境禁区。"""

from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.security import client_ip
from config.runtime import load_runtime
from config.settings import base

STRONG_KEY = "test-only-independent-secret-0123456789abcdefghijklmnopqrstuvwxyz"


def deployment_env(**overrides):
    values = {
        "APP_ENV": "prod",
        "DJANGO_SECRET_KEY": STRONG_KEY,
        "DB_HOST": "db.internal",
        "DB_NAME": "tiyoujie",
        "DB_USER": "tiyoujie",
        "DB_PASSWORD": "a-long-database-password",
        "REDIS_URL": "redis://:a-long-redis-password@redis.internal:6379/0",
        "DJANGO_ALLOWED_HOSTS": "tiyoujie.pxcore.com.cn",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://tiyoujie.pxcore.com.cn",
        "PRIVATE_STORAGE_ROOT": "/app/private",
        "DJANGO_DEBUG": "0",
        "DEV_LOGIN_ENABLED": "0",
    }
    values.update(overrides)
    return values


class ProxyHeaderTests(SimpleTestCase):
    """代理终结 TLS 后，Django 必须信任 X-Forwarded-Proto，否则会无限 301。"""

    def configure(self, environment):
        runtime = SimpleNamespace(
            environment=environment,
            secret_key=STRONG_KEY,
            hosts=["tiyoujie.pxcore.com.cn"],
            csrf_origins=["https://tiyoujie.pxcore.com.cn"],
            database={},
            redis_url="redis://localhost:6379/0",
        )
        with patch.object(base, "load_runtime", return_value=runtime):
            return base.configure(environment)

    def test_deployed_settings_trust_forwarded_proto(self):
        for environment in ("staging", "prod"):
            settings = self.configure(environment)
            self.assertEqual(
                settings["SECURE_PROXY_SSL_HEADER"],
                ("HTTP_X_FORWARDED_PROTO", "https"),
            )
            self.assertTrue(settings["SECURE_SSL_REDIRECT"])

    def test_deployed_settings_trust_forwarded_for(self):
        for environment in ("staging", "prod"):
            self.assertTrue(self.configure(environment)["TRUST_FORWARDED_FOR"])

    def test_local_settings_ignore_forwarded_proto(self):
        for environment in ("dev", "test"):
            settings = self.configure(environment)
            self.assertIsNone(settings["SECURE_PROXY_SSL_HEADER"])
            self.assertFalse(settings["SECURE_SSL_REDIRECT"])
            self.assertFalse(settings["TRUST_FORWARDED_FOR"])


class ClientIpTests(SimpleTestCase):
    """限流身份必须落到真实客户端 IP，否则代理后全体用户共用一个桶。"""

    def request(self, remote, forwarded=None):
        meta = {"REMOTE_ADDR": remote}
        if forwarded is not None:
            meta["HTTP_X_FORWARDED_FOR"] = forwarded
        return SimpleNamespace(META=meta)

    def test_uses_last_hop_when_behind_proxy(self):
        with override_settings(TRUST_FORWARDED_FOR=True):
            ip = client_ip(self.request("172.17.0.1", "1.2.3.4, 203.0.113.9"))
        # 前面的值客户端可伪造，只信任代理写入的最后一跳。
        self.assertEqual(ip, "203.0.113.9")

    def test_falls_back_to_remote_addr(self):
        with override_settings(TRUST_FORWARDED_FOR=True):
            self.assertEqual(client_ip(self.request("172.17.0.1")), "172.17.0.1")
            self.assertEqual(client_ip(self.request("172.17.0.1", "  ,  ")), "172.17.0.1")

    def test_ignores_spoofed_header_when_not_deployed(self):
        with override_settings(TRUST_FORWARDED_FOR=False):
            ip = client_ip(self.request("203.0.113.9", "10.0.0.1"))
        self.assertEqual(ip, "203.0.113.9")


class DeploymentGuardTests(SimpleTestCase):
    def test_accepts_well_formed_deployment_configuration(self):
        runtime = load_runtime("prod", env=deployment_env())
        self.assertEqual(runtime.hosts, ["tiyoujie.pxcore.com.cn"])
        self.assertEqual(runtime.csrf_origins, ["https://tiyoujie.pxcore.com.cn"])

    def test_rejects_weak_secret(self):
        for secret in ("changeme-changeme", "short", "a" * 60):
            with self.subTest(secret=secret[:12]):
                with self.assertRaises(ImproperlyConfigured):
                    load_runtime("prod", env=deployment_env(DJANGO_SECRET_KEY=secret))

    def test_rejects_http_csrf_origin(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime(
                "prod",
                env=deployment_env(DJANGO_CSRF_TRUSTED_ORIGINS="http://tiyoujie.pxcore.com.cn"),
            )

    def test_rejects_loopback_host_and_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", env=deployment_env(DJANGO_ALLOWED_HOSTS="localhost"))
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", env=deployment_env(DJANGO_DEBUG="1"))

    def test_rejects_unauthenticated_redis_and_dev_login(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", env=deployment_env(REDIS_URL="redis://redis:6379/0"))
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", env=deployment_env(DEV_LOGIN_ENABLED="1"))

    def test_rejects_test_database_outside_test_environment(self):
        with self.assertRaises(ImproperlyConfigured):
            load_runtime("prod", env=deployment_env(DB_NAME="tiyoujie_test"))


@override_settings(
    ALLOWED_HOSTS=["tiyoujie.pxcore.com.cn"],
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
class HttpsBehindProxyTests(TestCase):
    """回归：代理已终结 TLS 时不能再跳转，否则微信端会陷入 301 死循环。"""

    def test_forwarded_https_is_not_redirected(self):
        response = self.client.get(
            "/api/v1/health/live/",
            HTTP_HOST="tiyoujie.pxcore.com.cn",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(response.status_code, 200)

    def test_plain_http_is_redirected(self):
        response = self.client.get(
            "/api/v1/health/live/",
            HTTP_HOST="tiyoujie.pxcore.com.cn",
            HTTP_X_FORWARDED_PROTO="http",
        )
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))
