#!/usr/bin/env bash
# 把本项目的站点块安全地并入主机 Caddyfile。
#
# 设计前提：本机 Caddy 可能已经在为其它小程序服务，因此本脚本
#   * 只做“插入/替换本域名块”，绝不动其它站点；
#   * 改前备份、改后校验，校验失败自动回滚；
#   * 可重复执行（幂等），重复跑不会产生重复站点块。
#
# 用法：
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010 --dry-run
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --remove
set -euo pipefail

DOMAIN=""
UPSTREAM="18010"
CADDYFILE="/etc/caddy/Caddyfile"
DRY_RUN=0
REMOVE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/caddy/tiyoujie.caddy.template"

die() {
	printf '错误：%s\n' "$1" >&2
	exit 1
}
say() { printf '%s\n' "$1"; }

while [ $# -gt 0 ]; do
	case "$1" in
	--domain)
		DOMAIN="${2:-}"
		shift 2
		;;
	--upstream)
		UPSTREAM="${2:-}"
		shift 2
		;;
	--caddyfile)
		CADDYFILE="${2:-}"
		shift 2
		;;
	--dry-run)
		DRY_RUN=1
		shift
		;;
	--remove)
		REMOVE=1
		shift
		;;
	-h | --help)
		sed -n '2,16p' "$0"
		exit 0
		;;
	*)
		die "未知参数 $1"
		;;
	esac
done

[ -n "$DOMAIN" ] || die "必须提供 --domain，例如 tiyoujie.pxcore.com.cn"
case "$DOMAIN" in
*[!a-z0-9.-]*) die "域名只能包含小写字母、数字、点与连字符" ;;
esac
case "$UPSTREAM" in
'' | *[!0-9]*) die "--upstream 必须是端口号" ;;
esac
[ -f "$CADDYFILE" ] || die "找不到 $CADDYFILE"

START="# >>> tiyoujie ${DOMAIN} >>>"
END="# <<< tiyoujie ${DOMAIN} <<<"

strip_block() {
	awk -v start="$START" -v end="$END" '
		$0 == start { skip = 1; next }
		$0 == end { skip = 0; next }
		!skip
	' "$1"
}

render_block() {
	[ -f "$TEMPLATE" ] || die "找不到模板 $TEMPLATE"
	sed -e "s/__DOMAIN__/${DOMAIN}/g" -e "s/__UPSTREAM__/${UPSTREAM}/g" "$TEMPLATE"
}

validate_file() {
	local file="$1"
	if command -v caddy >/dev/null 2>&1; then
		caddy validate --config "$file" --adapter caddyfile >/dev/null 2>&1
	elif command -v docker >/dev/null 2>&1; then
		docker run --rm -v "${file}:/etc/caddy/Caddyfile:ro" caddy:2.10-alpine \
			caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
	else
		say "提示：本机既没有 caddy 也没有 docker，跳过语法校验。"
		return 0
	fi
}

reload_caddy() {
	if [ "$DRY_RUN" -eq 1 ]; then
		say "（预演）此处会重载 Caddy。"
		return 0
	fi
	if systemctl is-active --quiet caddy 2>/dev/null; then
		systemctl reload caddy
	elif command -v caddy >/dev/null 2>&1; then
		caddy reload --config "$CADDYFILE" --adapter caddyfile
	elif command -v docker >/dev/null 2>&1; then
		docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
	else
		die "无法重载 Caddy：请手动 systemctl reload caddy"
	fi
}

TMP="$(mktemp)"
BACKUP=""
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

if [ "$REMOVE" -eq 1 ]; then
	strip_block "$CADDYFILE" >"$TMP"
	if cmp -s "$TMP" "$CADDYFILE"; then
		say "Caddyfile 中没有 ${DOMAIN} 的块，无需删除。"
		exit 0
	fi
else
	{
		strip_block "$CADDYFILE"
		printf '\n%s\n' "$START"
		render_block
		printf '%s\n' "$END"
	} >"$TMP"
fi

if cmp -s "$TMP" "$CADDYFILE"; then
	say "Caddyfile 已是最新，无需改动。"
	exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
	say "===== 预演：以下内容将写入 $CADDYFILE ====="
	cat "$TMP"
	exit 0
fi

BACKUP="${CADDYFILE}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "$CADDYFILE" "$BACKUP"
say "已备份原配置：$BACKUP"

install -m 0644 "$TMP" "$CADDYFILE"
if ! validate_file "$CADDYFILE"; then
	cp -a "$BACKUP" "$CADDYFILE"
	die "Caddy 语法校验失败，已自动还原 $CADDYFILE"
fi
say "语法校验通过。"

if [ -d /var/log/caddy ]; then
	chown -R caddy:caddy /var/log/caddy 2>/dev/null || true
else
	mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy 2>/dev/null || true
fi

if ! reload_caddy; then
	cp -a "$BACKUP" "$CADDYFILE"
	reload_caddy || true
	die "重载失败，已还原 $CADDYFILE"
fi

say "完成：https://${DOMAIN}/ 已指向 127.0.0.1:${UPSTREAM}，证书由 Caddy 自动申请。"
say "首次申请证书通常 10-60 秒；可用 curl -I https://${DOMAIN}/api/v1/health/live/ 观察。"
