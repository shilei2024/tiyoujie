from config.celery import app


@app.task(ignore_result=True)
def execute_ocr(identifier):
    from .services import run_job

    run_job(identifier)


@app.task(ignore_result=True)
def recover_ocr():
    from .services import recover_jobs

    recover_jobs()
