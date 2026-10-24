#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    if "test" in sys.argv and (
        os.environ.get("APP_ENV") != "test"
        or os.environ["DJANGO_SETTINGS_MODULE"] != "config.settings.test"
    ):
        raise SystemExit("Tests must run through the isolated Compose test profile")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
