"""基础限额引导：生产曾因缺 ResourcePolicy 让创建家庭直接 503。

设计上要求"显式配置"是对的，但部署流程没有这一步，于是配置缺失只有在
真人点「创建家庭」时才暴露。这里锁住两件事：引导命令幂等、且绝不覆盖人工值。
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import AuditEvent
from apps.entitlements.models import ResourcePolicy
from apps.entitlements.services import policy


class EnsureBasePolicyTests(TestCase):
    def run_command(self, **options):
        out = StringIO()
        call_command("ensure_base_policy", stdout=out, **options)
        return out.getvalue()

    def test_creates_policy_when_absent(self):
        self.assertFalse(ResourcePolicy.objects.exists())
        self.run_command(basic_children=3, max_families=3)
        self.assertEqual(policy().basic_child_limit, 3)
        self.assertEqual(policy().max_families, 3)

    def test_writes_audit_trail(self):
        self.run_command(basic_children=2, max_families=2, reason="deploy bootstrap")
        event = AuditEvent.objects.get(action="base_policy_initialized")
        self.assertEqual(event.object_id, "base")
        self.assertEqual(event.reason, "deploy bootstrap")

    def test_never_overwrites_existing_values(self):
        ResourcePolicy.objects.create(basic_child_limit=5, max_families=7)
        output = self.run_command(basic_children=3, max_families=3)
        self.assertEqual(policy().basic_child_limit, 5)
        self.assertEqual(policy().max_families, 7)
        self.assertIn("未改动", output)

    def test_second_run_is_idempotent(self):
        self.run_command(basic_children=3, max_families=3)
        self.run_command(basic_children=3, max_families=3)
        self.assertEqual(ResourcePolicy.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="base_policy_initialized").count(), 1)

    def test_rejects_out_of_range_limits(self):
        with self.assertRaises(CommandError):
            self.run_command(basic_children=0, max_families=3)
        with self.assertRaises(CommandError):
            self.run_command(basic_children=3, max_families=99)
        self.assertFalse(ResourcePolicy.objects.exists())

    def test_unconfigured_site_refuses_family_creation(self):
        """没有兜底的情况下必须显式报错，不能静默放行成无限额度。"""
        from apps.accounts.services import create_family
        from config.errors import AppError

        user = self._user()
        with self.assertRaises(AppError) as caught:
            create_family(user, "无配置家庭")
        self.assertEqual(caught.exception.public_code, "SITE_NOT_CONFIGURED")

    def _user(self):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username="bootstrap-guardian")
