from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import AuditEvent
from apps.entitlements.models import ResourcePolicy


class Command(BaseCommand):
    help = "Explicitly configure base resource limits; does not activate any promotion."

    def add_arguments(self, parser):
        parser.add_argument("--basic-children", type=int, required=True)
        parser.add_argument("--max-families", type=int, required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        if (
            not 1 <= options["basic_children"] <= 100
            or not 1 <= options["max_families"] <= 20
            or not options["reason"].strip()
        ):
            raise CommandError("Invalid limits or missing reason")
        ResourcePolicy.objects.update_or_create(
            pk="base",
            defaults={
                "basic_child_limit": options["basic_children"],
                "max_families": options["max_families"],
            },
        )
        AuditEvent.objects.create(
            action="base_policy_configured", object_id="base", reason=options["reason"][:200]
        )
        self.stdout.write("Base policy configured; no campaign activated.")
