from django.conf import settings

from config.celery import app

if settings.APP_ENV == "test":

    @app.task(name="infrastructure.test_probe")
    def test_probe(nonce):
        return {"nonce": nonce, "environment": "test"}
