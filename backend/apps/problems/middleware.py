from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import JsonResponse


class BoundedUpload(FileUploadHandler):
    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > settings.IMAGE_MAX_BYTES:
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None


class RequestSizeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = (
            settings.IMAGE_MAX_BYTES + 65536
            if request.content_type == "multipart/form-data"
            else 65536
        )
        try:
            size = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            size = limit + 1
        if size < 0 or size > limit:
            return JsonResponse(
                {
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "请求内容超过限额。",
                        "request_id": request.request_id,
                    }
                },
                status=413,
            )
        return self.get_response(request)
