from config.celery import app


@app.task(ignore_result=True)
def cleanup_private_objects():
    from .services import cleanup_objects

    cleanup_objects()
