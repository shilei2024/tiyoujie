from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import AuditEvent
from apps.entitlements.models import ResourcePolicy


class Command(BaseCommand):
    """幂等地保证基础限额存在；已存在时绝不覆盖人工配置。

    这不是"悄悄启用活动"：PromotionCampaign 依旧只能显式创建。
    基础限额是产品底座，缺了会让创建家庭、添加档案直接 503，
    属于"必须先于第一个用户存在"的配置，因此纳入部署流程。
    """

    help = "Create base resource limits only when absent; never overwrite existing values."

    def add_arguments(self, parser):
        parser.add_argument("--basic-children", type=int, default=3)
        parser.add_argument("--max-families", type=int, default=3)
        parser.add_argument("--reason", default="deployment bootstrap")

    def handle(self, *args, **options):
        children = options["basic_children"]
        families = options["max_families"]
        reason = (options["reason"] or "").strip()
        if not 1 <= children <= 100 or not 1 <= families <= 20 or not reason:
            raise CommandError("Invalid limits or missing reason")

        existing = ResourcePolicy.objects.filter(pk="base").first()
        if existing:
            self.stdout.write(
                "基础限额已存在，未改动："
                f"basic_child_limit={existing.basic_child_limit} "
                f"max_families={existing.max_families}"
            )
            return

        ResourcePolicy.objects.create(pk="base", basic_child_limit=children, max_families=families)
        AuditEvent.objects.create(
            action="base_policy_initialized", object_id="base", reason=reason[:200]
        )
        self.stdout.write(
            f"基础限额缺失，已初始化：basic_child_limit={children} max_families={families}；"
            "如需调整请用 configure_limits（会记录原因）"
        )
