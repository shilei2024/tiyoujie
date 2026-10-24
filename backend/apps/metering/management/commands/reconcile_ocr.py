from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.metering.services import reconcile
from apps.ocr.models import OCRJob
from config.errors import AppError


class Command(BaseCommand):
    help = "Settle an unknown platform cost using verified supplier evidence; circuit stays halted."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--job", required=True)
        parser.add_argument("--amount-micros", type=int, required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["actor_id"]).first()
        if not actor:
            raise CommandError("Operator not found")
        job = OCRJob.objects.filter(pk=options["job"]).first()
        if not job:
            raise CommandError("Task not found")
        try:
            reconcile(actor, job, options["amount_micros"], options["reason"])
        except AppError:
            raise CommandError("Reconciliation rejected; check status and permissions") from None
        self.stdout.write("Cost reconciled; circuit remains halted until an audited policy edit.")
