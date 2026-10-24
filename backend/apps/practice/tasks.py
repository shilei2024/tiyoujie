from config.celery import app


@app.task(ignore_result=True)
def cleanup_export_tickets():
    from .services import cleanup_exports

    cleanup_exports()
