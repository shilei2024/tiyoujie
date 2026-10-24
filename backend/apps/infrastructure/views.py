from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .health import readiness


class LiveView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "tiyoujie", "ai": "disabled"})


class ReadyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        checks = readiness()
        ready = all(value == "ok" for value in checks.values())
        return Response(
            {"status": "ready" if ready else "unavailable", "checks": checks, "ai": "disabled"},
            status=200 if ready else 503,
        )
