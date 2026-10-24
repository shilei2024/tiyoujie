#!/usr/bin/env bash
# 校验小程序 AppSecret 真实有效（不只是“变量非空”）。
#
# 只做一件事：用 .env.prod 里的 AppID/AppSecret 向微信换取 access_token。
# 换到了 = 密钥有效 + 服务器出网可达 + IP 未被白名单拦截；换不到 = 按 errcode 给出原因。
# 全程不打印、不回显 AppSecret 与 access_token。
#
# 用法（服务器 /opt/tiyoujie/repo 下）：
#   ./infra/deploy/verify-wechat.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_DIR}/.env.prod"
DOMAIN="tiyoujie.pxcore.com.cn"

command -v python3 >/dev/null 2>&1 || {
	printf '错误：缺少 python3\n' >&2
	exit 1
}
[ -f "$ENV_FILE" ] || {
	printf '错误：找不到 %s\n' "$ENV_FILE" >&2
	exit 1
}

env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

APP_ID="$(env_value WECHAT_APP_ID)"
APP_SECRET="$(env_value WECHAT_APP_SECRET)"
DOMAIN="$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f1)"
[ -n "$DOMAIN" ] || DOMAIN="tiyoujie.pxcore.com.cn"

printf '== 1/3 配置存在性 ==\n'
if [ -z "$APP_ID" ]; then
	printf '失败：.env.prod 缺少 WECHAT_APP_ID\n' >&2
	exit 1
fi
printf 'AppID：%s\n' "$APP_ID"
if [ -z "$APP_SECRET" ]; then
	printf '失败：.env.prod 缺少 WECHAT_APP_SECRET（这就是登录返回 503 的原因）\n' >&2
	printf '      写入方式见 docs/operations/go-live-manual-steps.md 第 3.3 节\n' >&2
	exit 1
fi
printf 'AppSecret：已配置（长度 %s，不显示内容）\n' "${#APP_SECRET}"

printf '\n== 2/3 向微信换取 access_token ==\n'
# 密钥经环境变量传入，避免出现在 ps / 命令行参数里。
# set -e 下要显式接住非零退出码，否则脚本会在打印诊断前直接终止。
TOKEN_STATUS=0
WX_ID="$APP_ID" WX_SECRET="$APP_SECRET" python3 - <<'PY' || TOKEN_STATUS=$?
import json
import os
import sys
import urllib.error
import urllib.request

payload = json.dumps(
    {
        "grant_type": "client_credential",
        "appid": os.environ["WX_ID"],
        "secret": os.environ["WX_SECRET"],
        "force_refresh": False,
    }
).encode()
request = urllib.request.Request(
    "https://api.weixin.qq.com/cgi-bin/stable_token",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

HINTS = {
    40013: "AppID 无效：与小程序后台的 AppID 不一致",
    40125: "AppSecret 无效：后台重置过密钥，需同步为最新值",
    40164: "调用 IP 不在白名单：把本机公网 IP 加入小程序后台 IP 白名单，或关闭白名单",
    41004: "缺少 secret 参数",
    45009: "接口调用次数超限，稍后再试",
    89503: "需要管理员确认后才允许调用",
    -1: "微信侧系统繁忙，稍后重试",
}

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read().decode())
except urllib.error.URLError as error:
    print(f"失败：无法连接 api.weixin.qq.com（{error.reason}）")
    print("      说明服务器出网被拦；小程序登录同样会失败，需先放通 443 出网")
    sys.exit(2)
except TimeoutError:
    print("失败：连接 api.weixin.qq.com 超时；服务器出网不通")
    sys.exit(2)

code = body.get("errcode", 0)
if code == 0 and body.get("access_token"):
    print(f"成功：已获取 access_token（长度 {len(body['access_token'])}，不显示内容）")
    print(f"      有效期 {body.get('expires_in', '?')} 秒")
    sys.exit(0)

print(f"失败：errcode={code} errmsg={body.get('errmsg', '')}")
hint = HINTS.get(code)
if hint:
    print(f"      原因：{hint}")
else:
    print("      原因未知，请把 errcode 连同小程序后台配置一并核对")
sys.exit(1)
PY

printf '\n== 3/3 线上能力声明 ==\n'
curl -sS "https://${DOMAIN}/api/v1/auth/capabilities/" || {
	printf '\n失败：无法访问 https://%s\n' "$DOMAIN" >&2
	exit 1
}
printf '\n'

if [ "$TOKEN_STATUS" -ne 0 ]; then
	printf '\n结论：AppSecret 未通过微信校验，先修 2/3 的报错，再看 3/3 是否变为\n' >&2
	printf '      "wechat_configured": true。仅变量非空不足以让用户登录成功。\n' >&2
	exit 1
fi

printf '\n结论：密钥有效。若 3/3 仍是 "wechat_configured": false，说明 API 进程没重启，执行：\n'
printf '      cd %s && docker compose -p tiyoujie --env-file .env.prod \\\n' "$REPO_DIR"
printf '        -f compose.yaml -f infra/deploy/compose.prod.yaml up -d --wait --no-build api worker beat\n'
