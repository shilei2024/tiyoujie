from django.core.management.base import BaseCommand

from apps.credentials.services import rotate_master_key


class Command(BaseCommand):
    help = "Re-encrypt active credentials using a configured key version; never display keys."

    def add_arguments(self, parser):
        parser.add_argument("--to-version", required=True)

    def handle(self, *args, **options):
        count = rotate_master_key(options["to_version"])
        self.stdout.write(f"Re-encrypted {count} credentials; plaintext suppressed.")
