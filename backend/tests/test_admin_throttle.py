"""后台登录限流回归：admin 挂在公网域名上，必须防撞库。"""

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from redis import Redis


class AdminLoginThrottleTests(TestCase):
    """按 IP 计数，超过阈值返回 429，且不误伤页面本身。"""

    def setUp(self):
        # 计数落在真实 Redis 上，不会随事务回滚；每个用例自己清干净，
        # 否则前一个用例的计数会把后一个用例直接顶到阈值外。
        with Redis.from_url(settings.REDIS_URL) as client:
            for key in client.scan_iter(
                f"limit:{settings.AUTH_THROTTLE_NAMESPACE}:admin_login:*", count=100
            ):
                client.delete(key)

    def post_login(self, password="guess"):
        return self.client.post(
            reverse("admin:login"),
            {"username": "nobody", "password": password, "next": "/admin/"},
            REMOTE_ADDR="203.0.113.9",
        )

    def test_login_page_stays_reachable(self):
        response = self.client.get(reverse("admin:login"), REMOTE_ADDR="203.0.113.9")
        self.assertEqual(response.status_code, 200)

    def test_repeated_failures_are_throttled(self):
        codes = [self.post_login().status_code for _ in range(settings.ADMIN_LOGIN_LIMIT_COUNT + 1)]
        self.assertEqual(
            codes[: settings.ADMIN_LOGIN_LIMIT_COUNT], [200] * settings.ADMIN_LOGIN_LIMIT_COUNT
        )
        self.assertEqual(codes[-1], 429)

        throttled = self.post_login()
        self.assertEqual(
            throttled.json()["error"]["code"],
            "RATE_LIMITED",
        )

    def test_threshold_is_tighter_than_business_api(self):
        """后台阈值必须比业务接口紧，否则这条防护没有意义。"""
        self.assertLess(settings.ADMIN_LOGIN_LIMIT_COUNT, settings.AUTH_RATE_LIMIT_COUNT)

    @override_settings(ADMIN_LOGIN_LIMIT_COUNT=2)
    def test_threshold_is_configurable(self):
        statuses = [self.post_login().status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    def test_other_ip_has_its_own_bucket(self):
        for _ in range(settings.ADMIN_LOGIN_LIMIT_COUNT):
            self.post_login()
        response = self.client.post(
            reverse("admin:login"),
            {"username": "nobody", "password": "guess"},
            REMOTE_ADDR="203.0.113.10",
        )
        self.assertEqual(response.status_code, 200)
