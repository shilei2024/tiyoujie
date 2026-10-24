import json
import logging
import time
import uuid


class SafeJSONFormatter(logging.Formatter):
    """A field allowlist: never format message arguments, bodies, headers or tracebacks."""

    def format(self, record):
        data = {"level": record.levelname, "event": getattr(record, "event", "service_event")}
        for name in ("request_id", "status", "duration_ms"):
            value = getattr(record, name, None)
            if value is not None:
                data[name] = value
        return json.dumps(data, ensure_ascii=False)


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex
        start = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        response["Cache-Control"] = "no-store"
        logging.getLogger("http").info(
            "http",
            extra={
                "event": "http_request",
                "request_id": request.request_id,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000, 2),
            },
        )
        return response
