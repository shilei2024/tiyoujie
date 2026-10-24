import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from redis import Redis
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from config.errors import AppError

from .models import AuthSession, RefreshToken


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def client_ip(request):
    """取真实客户端 IP。

    生产环境前面有一层边缘代理（Caddy），Django 看到的 REMOTE_ADDR 永远是代理地址，
    直接拿它做限流会让所有用户共用一个桶：正常用户会被别人拖慢，攻击者也只需打满
    一个桶就能让全部人登录失败。只有确认自己部署在代理之后（deployed）才信任
    X-Forwarded-For，并且取**最后一跳**——前面的值是客户端可以随便伪造的。
    """
    if settings.TRUST_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(request, operation="auth"):
    identity = str(request.user.pk) if request.user.is_authenticated else client_ip(request)
    identity = hmac.new(settings.SECRET_KEY.encode(), identity.encode(), hashlib.sha256).hexdigest()
    key = f"limit:{settings.AUTH_THROTTLE_NAMESPACE}:{operation}:{identity}"
    script = (
        "local n=redis.call('INCR',KEYS[1]); "
        "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n"
    )
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2
        ) as client:
            count = client.eval(script, 1, key)
    except Exception:
        raise AppError(
            "AUTH_LIMITER_UNAVAILABLE", "暂时无法验证请求频率，请稍后重试。", 503
        ) from None
    if count > settings.AUTH_RATE_LIMIT_COUNT:
        raise AppError("RATE_LIMITED", "操作过于频繁，请一分钟后重试。", 429)


def _tokens(session):
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    session.access_hash = digest(access)
    session.access_expires_at = timezone.now() + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    session.save()
    RefreshToken.objects.create(session=session, token_hash=digest(refresh))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": session.access_expires_at,
        "user": {"id": session.user_id, "is_test_login": session.is_test_login},
    }


@transaction.atomic
def issue_session(user, is_test=False):
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "账号不可用。", 403)
    session = AuthSession(
        user=user,
        expires_at=timezone.now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
        is_test_login=is_test,
    )
    return _tokens(session)


def refresh_session(token):
    entry = RefreshToken.objects.filter(token_hash=digest(token)).first()
    if not entry:
        raise AppError("AUTH_INVALID", "登录已失效，请重新登录。", 401)
    reused = False
    with transaction.atomic():
        session = (
            AuthSession.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=entry.session_id)
        )
        entry = RefreshToken.objects.select_for_update().get(pk=entry.pk)
        now = timezone.now()
        if session.revoked_at or session.expires_at <= now or not session.user.is_active:
            raise AppError("AUTH_INVALID", "登录已失效，请重新登录。", 401)
        if entry.used_at:
            session.revoked_at = now
            session.save(update_fields=["revoked_at"])
            reused = True
        else:
            entry.used_at = now
            entry.save(update_fields=["used_at"])
            result = _tokens(session)
    if reused:
        raise AppError("REFRESH_REUSED", "检测到重复登录凭证，请重新登录。", 401)
    return result


class BearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].lower() != b"bearer" or len(header[1]) > 256:
            raise AuthenticationFailed("登录凭证无效")
        try:
            token = header[1].decode("ascii")
        except UnicodeDecodeError:
            raise AuthenticationFailed("登录凭证无效") from None
        now = timezone.now()
        session = (
            AuthSession.objects.select_related("user")
            .filter(
                access_hash=digest(token),
                revoked_at__isnull=True,
                access_expires_at__gt=now,
                expires_at__gt=now,
                user__is_active=True,
            )
            .first()
        )
        if not session:
            raise AuthenticationFailed("登录已失效")
        return session.user, session

    def authenticate_header(self, request):
        return "Bearer"
