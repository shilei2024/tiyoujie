from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.entitlements.services import manual_grant
from config.errors import AppError


class Command(BaseCommand):
    help = "Issue a campaign entitlement as a permitted operator, with a mandatory audit reason."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", required=True, type=int)
        parser.add_argument("--family", required=True)
        parser.add_argument("--campaign", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["actor_id"]).first()
        try:
            grant = manual_grant(actor, options["family"], options["campaign"], options["reason"])
        except (AppError, ValueError):
            raise CommandError("Entitlement issuance rejected; check scope and operator.") from None
        self.stdout.write(f"Entitlement issued: {grant.pk}")
