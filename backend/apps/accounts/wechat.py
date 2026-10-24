import json
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from config.errors import AppError

from .models import AuthIdentity


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange_code(code):
    if not settings.WECHAT_APP_ID or not settings.WECHAT_APP_SECRET:
        raise AppError("WECHAT_NOT_CONFIGURED", "微信登录尚未配置。", 503)
    query = urlencode(
        {
            "appid": settings.WECHAT_APP_ID,
            "secret": settings.WECHAT_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        request = Request("https://api.weixin.qq.com/sns/jscode2session?" + query)
        with build_opener(NoRedirect).open(request, timeout=5) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError()
        result = json.loads(body)
    except (HTTPError, OSError, ValueError):
        raise AppError("WECHAT_UNAVAILABLE", "微信服务暂不可用，请重试。", 503) from None
    if not isinstance(result, dict) or result.get("errcode", 0):
        raise AppError("WECHAT_CODE_INVALID", "微信登录凭证无效或已过期。", 400)
    subject = result.get("openid")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 128:
        raise AppError("WECHAT_RESPONSE_INVALID", "微信响应不完整，请重新登录。", 503)
    return subject


def identity_user(provider, app_id, subject):
    lookup = {"provider": provider, "app_id": app_id, "subject": subject}
    identity = AuthIdentity.objects.filter(**lookup).select_related("user").first()
    if identity:
        return identity.user
    try:
        with transaction.atomic():
            user = get_user_model().objects.create_user(username="account_" + uuid.uuid4().hex)
            AuthIdentity.objects.create(user=user, **lookup)
            return user
    except IntegrityError:
        return AuthIdentity.objects.select_related("user").get(**lookup).user
