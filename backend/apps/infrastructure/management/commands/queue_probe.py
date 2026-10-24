import json
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify the isolated test Redis and actual Linux worker round trip."

    def handle(self, *args, **options):
        if settings.APP_ENV != "test":
            raise CommandError("Queue probe is only available in the isolated test environment")
        from apps.infrastructure.tasks import test_probe

        nonce = uuid.uuid4().hex
        task = test_probe.delay(nonce)
        try:
            result = task.get(timeout=30)
            if result != {"nonce": nonce, "environment": "test"}:
                raise CommandError("Unexpected queue probe result")
            self.stdout.write(json.dumps({"task_id": task.id, "status": "succeeded", **result}))
        finally:
            task.forget()
