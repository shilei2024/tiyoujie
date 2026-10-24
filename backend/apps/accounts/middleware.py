from django.conf import settings
from django.http import JsonResponse

from config.errors import AppError

from .security import rate_limit


class AdminLoginThrottle:
    """给 /admin/login/ 的 POST 加按 IP 限流。

    Django admin 自带登录页没有任何防爆破机制，而本项目 admin 挂在公网域名上
    （题库审核、预算策略都在里面）。没有限流时，它可以被无限次撞库。

    这里返回 429 而不是 403/404：admin 登录页本来就对外可达，隐藏它没意义，
    明确告诉对方“被限速了”比伪装成不存在更诚实，也不会误导运维排查。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path.rstrip("/") == "/admin/login":
            try:
                rate_limit(request, "admin_login", count=settings.ADMIN_LOGIN_LIMIT_COUNT)
            except AppError as error:
                return JsonResponse(
                    {
                        "error": {
                            "code": error.public_code,
                            "message": error.public_message,
                        }
                    },
                    status=error.status_code,
                )
        return self.get_response(request)
