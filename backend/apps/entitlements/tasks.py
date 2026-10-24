from config.celery import app


@app.task(ignore_result=True)
def reconcile_entitlements():
    from .services import process_entitlements

    process_entitlements()
