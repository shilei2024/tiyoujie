import logging

from rest_framework.exceptions import APIException
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class AppError(APIException):
    def __init__(self, code, message, status=400):
        self.status_code = status
        self.public_code = code
        self.public_message = message
        super().__init__(message)


def exception_handler(exc, context):
    from django.core.exceptions import SuspiciousOperation
    from rest_framework.views import exception_handler as drf_exception_handler

    if isinstance(exc, SuspiciousOperation):
        exc = AppError("INVALID_REQUEST", "请求内容或上传数量超过限制。", 400)
    response = drf_exception_handler(exc, context)
    request_id = getattr(context.get("request"), "request_id", "unknown")
    if response is None:
        logger.error("api_failure", extra={"event": "api_failure", "request_id": request_id})
        return Response({"error": {"code": "INTERNAL_ERROR", "request_id": request_id}}, status=500)
    codes = {
        400: "INVALID_REQUEST",
        401: "AUTH_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
    }
    response.data = {
        "error": {
            "code": getattr(
                exc, "public_code", codes.get(response.status_code, "REQUEST_REJECTED")
            ),
            "message": getattr(exc, "public_message", "请求未通过校验或没有访问权限。"),
            "request_id": request_id,
        }
    }
    return response
