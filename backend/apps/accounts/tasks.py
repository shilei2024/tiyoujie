from config.celery import app


@app.task(ignore_result=True)
def process_deletions():
    from .services import process_pending_deletions

    process_pending_deletions()
