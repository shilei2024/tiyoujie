from django.apps import AppConfig


class ProblemsConfig(AppConfig):
    name = "apps.problems"

    def ready(self):
        from . import signals  # noqa: F401
