#!/usr/bin/env bash
# 轮换小程序 AppID + AppSecret：新的 AppID/Secret 配对验证通过后，才原子替换 .env.prod。
#
# 为什么要成对换、且先验证：
#   - 只换 AppID 留着旧 Secret → 微信返回 40013/40125，登录全挂；
#   - 先写文件再验证 → 写坏了要靠手抄备份回滚，中间是登录不可用的空窗；
#   - AppID 决定 openid 归属，换了 AppID 等于换身份空间，老用户会变成新账号，
#     并且小程序端必须用新 AppID 重新构建、重新上传、重新配域名白名单。
# 本脚本顺序：校验格式 → 向微信换 token → 备份 → 原子写入 → 重启 → 复验。
# 任何一步失败都不会修改 .env.prod。
#
# 用法（服务器 /opt/tiyoujie/repo 下，二选一）：
#   交互式（推荐，密钥不进 shell 历史）：
#       ./infra/deploy/rotate-wechat-credentials.sh --restart
#   环境变量：
#       WX_NEW_APP_ID=wx... WX_NEW_APP_SECRET=... ./infra/deploy/rotate-wechat-credentials.sh --restart
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${WX_ENV_FILE:-${REPO_DIR}/.env.prod}"
RESTART=0

for arg in "$@"; do
	case "$arg" in
	--restart) RESTART=1 ;;
	-h | --help)
		sed -n '2,20p' "$0"
		exit 0
		;;
	*) printf '未知参数 %s\n' "$arg" >&2 ;;
	esac
done

say() { printf '\n== %s ==\n' "$1"; }
die() {
	printf '失败：%s\n' "$1" >&2
	exit 1
}

command -v python3 >/dev/null 2>&1 || die "缺少 python3"
[ -f "$ENV_FILE" ] || die "找不到 $ENV_FILE"

env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

OLD_APP_ID="$(env_value WECHAT_APP_ID)"

say "1/5 读取新凭据"
NEW_APP_ID="${WX_NEW_APP_ID:-}"
NEW_APP_SECRET="${WX_NEW_APP_SECRET:-}"
if [ -z "$NEW_APP_ID" ]; then
	printf '新 AppID（wx 开头 18 位）：'
	read -r NEW_APP_ID
fi
if [ -z "$NEW_APP_SECRET" ]; then
	printf '新 AppSecret（输入不显示）：'
	read -rsp '' NEW_APP_SECRET
	printf '\n'
fi

say "2/5 校验格式"
if ! printf '%s' "$NEW_APP_ID" | grep -Eq '^wx[0-9a-fA-F]{16}$'; then
	die "AppID 格式不对：应为 wx + 16 位十六进制（当前输入长度 ${#NEW_APP_ID}）"
fi
if [ "${#NEW_APP_SECRET}" -ne 32 ]; then
	die "AppSecret 长度应为 32，实际 ${#NEW_APP_SECRET}（常见于复制时多带空格或只复制了一半）"
fi
if ! printf '%s' "$NEW_APP_SECRET" | grep -Eq '^[A-Za-z0-9]+$'; then
	die "AppSecret 只能是字母数字；带空格、引号或换行会破坏 .env 解析"
fi
printf 'AppID：%s\n' "$NEW_APP_ID"
printf 'AppSecret：已接收（长度 %s，不显示内容）\n' "${#NEW_APP_SECRET}"
if [ "$NEW_APP_ID" = "$OLD_APP_ID" ]; then
	printf '注意：AppID 与线上一致（%s），本次实际只更换 Secret\n' "$OLD_APP_ID"
else
	printf 'AppID 将从 %s 换成 %s\n' "${OLD_APP_ID:-（空）}" "$NEW_APP_ID"
fi

say "3/5 用新凭据向微信换 access_token"
TOKEN_STATUS=0
WX_ID="$NEW_APP_ID" WX_SECRET="$NEW_APP_SECRET" python3 - <<'PY' || TOKEN_STATUS=$?
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
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError) as error:
    print(f"无法连接微信接口：{error}", file=sys.stderr)
    sys.exit(1)

reasons = {
    40013: "AppID 不合法（多半是填错或与 Secret 不配套）",
    40125: "AppSecret 无效（在微信后台重置后未同步，或复制不完整）",
    40164: "服务器出口 IP 不在该小程序的 IP 白名单里",
    41004: "缺少 AppSecret",
    45009: "接口调用超过当日限额",
    -1: "微信侧繁忙，稍后重试",
}
code = body.get("errcode", 0)
if code:
    print(f"微信拒绝：errcode={code} {body.get('errmsg', '')}", file=sys.stderr)
    print(f"含义：{reasons.get(code, '未知错误，请核对 AppID/AppSecret 所属同一个小程序')}", file=sys.stderr)
    sys.exit(1)
token = body.get("access_token") or ""
if not token:
    print("微信未返回 access_token", file=sys.stderr)
    sys.exit(1)
print(f"成功：已换到 access_token（长度 {len(token)}，不显示内容）")
print(f"      有效期 {body.get('expires_in', '未知')} 秒")
PY
if [ "$TOKEN_STATUS" -ne 0 ]; then
	printf '\n.env.prod 未被修改（验证在写入之前）。\n' >&2
	exit 1
fi

say "4/5 备份并原子写入 .env.prod"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${ENV_FILE}.bak-${STAMP}"
cp -p "$ENV_FILE" "$BACKUP"
chmod 600 "$BACKUP"
printf '备份：%s\n' "$BACKUP"

WX_ID="$NEW_APP_ID" WX_SECRET="$NEW_APP_SECRET" WX_PATH="$ENV_FILE" python3 - <<'PY'
import os
import pathlib
import tempfile

path = pathlib.Path(os.environ["WX_PATH"])
values = {"WECHAT_APP_ID": os.environ["WX_ID"], "WECHAT_APP_SECRET": os.environ["WX_SECRET"]}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0]
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")

# 同目录临时文件 + os.replace，避免写入中途失败留下半截 .env
fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.prod.", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
    stream.write("\n".join(out) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("已写入：WECHAT_APP_ID / WECHAT_APP_SECRET（其余行原样保留）")
PY

say "5/5 生效与复验"
if [ "$RESTART" -eq 1 ]; then
	docker compose \
		--project-directory "$REPO_DIR" \
		--env-file "$ENV_FILE" \
		-f "$REPO_DIR/compose.yaml" \
		-f "$REPO_DIR/infra/deploy/compose.prod.yaml" \
		-p tiyoujie \
		up -d --wait --no-build api worker beat
	bash "${REPO_DIR}/infra/deploy/verify-wechat.sh" || {
		printf '\n复验未通过。回滚命令：\n  cp -p %s %s && docker compose --project-directory %s --env-file %s -f %s/compose.yaml -f %s/infra/deploy/compose.prod.yaml -p tiyoujie up -d --wait --no-build api worker beat\n' \
			"$BACKUP" "$ENV_FILE" "$REPO_DIR" "$ENV_FILE" "$REPO_DIR" "$REPO_DIR" >&2
		exit 1
	}
else
	printf '未加 --restart，配置尚未生效。执行：\n'
	printf '  cd %s && docker compose --project-directory . --env-file .env.prod -f compose.yaml -f infra/deploy/compose.prod.yaml -p tiyoujie up -d --wait --no-build api worker beat\n' "$REPO_DIR"
fi

cat <<EOF

== 换 AppID 后必须跟着做的三件事（顺序不能反）==
1) 新账号后台：开发管理 → 开发设置 → 服务器域名，request/uploadFile/downloadFile 都填
   https://tiyoujie.pxcore.com.cn    （不带路径、不带端口）
2) 本机用新 AppID 重新构建并上传（旧的 0.1.0 属于旧账号，不会出现在新账号里）：
   py -3.12 scripts/wechat.py build --appid ${NEW_APP_ID} --api-base https://tiyoujie.pxcore.com.cn
   py -3.12 scripts/wechat.py upload --appid ${NEW_APP_ID} --api-base https://tiyoujie.pxcore.com.cn --version 0.1.0
3) 新账号设为体验版并加体验成员，再真机登录。

身份影响：openid 与 AppID 绑定，换 AppID 后同一微信登录会得到全新账号，旧账号数据不会自动迁移。
EOF
