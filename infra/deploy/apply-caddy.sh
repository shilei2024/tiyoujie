#!/usr/bin/env bash
# 把本项目的站点块安全地并入主机上**容器化 Caddy** 的 Caddyfile。
#
# 目标主机实测形态（2026-10-24）：
#   * Caddy 跑在容器 mindfulpenpal-ai-production-caddy-1（caddy:2.10-alpine）；
#   * 它的 Caddyfile 是 bind mount：
#       /opt/mytoolbox/services/generation-service/deploy/Caddyfile.production
#       -> /etc/caddy/Caddyfile
#   * 同一份配置里还有 mindfulpenpal.com、api.pxcore.com.cn（另一个小程序）等站点块。
#
# 因此本脚本：
#   * 只做“插入/替换本域名块”，绝不触碰其它站点块；
#   * 改前备份、改后校验，校验或重载失败自动回滚；
#   * 幂等，重复执行不会产生重复站点块。
#
# 用法：
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010 --dry-run
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010
#   sudo ./apply-caddy.sh --domain tiyoujie.pxcore.com.cn --remove
set -euo pipefail

DOMAIN=""
UPSTREAM="18010"
CADDYFILE=""
CADDY_CONTAINER=""
BACKUP_DIR="/opt/tiyoujie/backups/caddy"
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
	--container)
		CADDY_CONTAINER="${2:-}"
		shift 2
		;;
	--backup-dir)
		BACKUP_DIR="${2:-}"
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
		sed -n '2,22p' "$0"
		exit 0
		;;
	*) die "未知参数 $1" ;;
	esac
done

[ -n "$DOMAIN" ] || die "必须提供 --domain，例如 tiyoujie.pxcore.com.cn"
case "$DOMAIN" in
*[!a-z0-9.-]*) die "域名只能包含小写字母、数字、点与连字符" ;;
esac
case "$UPSTREAM" in
'' | *[!0-9]*) die "--upstream 必须是端口号" ;;
esac

command -v docker >/dev/null 2>&1 || die "本机没有 docker"

# 自动识别：正在发布 443 的 caddy 容器，以及它的 Caddyfile 在宿主机上的路径。
if [ -z "$CADDY_CONTAINER" ]; then
	CADDY_CONTAINER="$(docker ps --filter "publish=443" --format '{{.Names}} {{.Image}}' |
		awk '$2 ~ /^caddy[:@]/ {print $1; exit}')"
fi
[ -n "$CADDY_CONTAINER" ] || die "找不到发布 443 端口的 caddy 容器，请用 --container 指定"

MOUNT_INFO="$(docker inspect "$CADDY_CONTAINER" --format \
	'{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}{{"\n"}}{{end}}' |
	grep -F '|/etc/caddy/Caddyfile' || true)"
[ -n "$MOUNT_INFO" ] || die "容器 ${CADDY_CONTAINER} 的 Caddyfile 不是 bind mount，本脚本不支持该形态"
CONTAINER_PATH="/etc/caddy/Caddyfile"
MOUNT_SOURCE="$(printf '%s' "$MOUNT_INFO" | head -1 | cut -d'|' -f2)"

if [ -z "$CADDYFILE" ]; then
	CADDYFILE="$MOUNT_SOURCE"
fi
[ -f "$CADDYFILE" ] || die "找不到 Caddyfile：$CADDYFILE"
[ "$CADDYFILE" = "$MOUNT_SOURCE" ] ||
	die "传入的 --caddyfile ($CADDYFILE) 与容器挂载源 ($MOUNT_SOURCE) 不一致，会导致校验结果失真"

say "Caddy 容器：${CADDY_CONTAINER}"
say "Caddyfile：${CADDYFILE}（容器内 ${CONTAINER_PATH}）"

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

# 在真实容器里校验：文件是 bind mount，改完立刻可见，且能拿到真实环境变量
# （例如 {$GENERATION_API_DOMAIN}），单独起临时容器会因缺变量误报失败。
validate_file() {
	docker exec "$CADDY_CONTAINER" caddy validate \
		--config "$CONTAINER_PATH" --adapter caddyfile >/dev/null 2>&1
}

reload_caddy() {
	docker exec "$CADDY_CONTAINER" caddy reload \
		--config "$CONTAINER_PATH" --adapter caddyfile >/dev/null 2>&1
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

mkdir -p "$BACKUP_DIR"
BACKUP="${BACKUP_DIR}/Caddyfile.production.$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "$CADDYFILE" "$BACKUP"
say "已备份原配置：$BACKUP"

# 保留原文件权限再写入，避免容器内外权限不一致。
install -m "$(stat -c '%a' "$BACKUP")" "$TMP" "$CADDYFILE"

if ! validate_file; then
	cp -a "$BACKUP" "$CADDYFILE"
	die "Caddy 语法校验失败，已自动还原 $CADDYFILE"
fi
say "语法校验通过（在真实容器内执行）。"

if ! reload_caddy; then
	cp -a "$BACKUP" "$CADDYFILE"
	reload_caddy || say "警告：回滚后的重载也失败了，请人工检查 docker logs ${CADDY_CONTAINER}"
	die "重载失败，已还原 $CADDYFILE"
fi

say "完成：https://${DOMAIN}/ 已指向 host.docker.internal:${UPSTREAM}。"
say "证书由 Caddy 自动申请，通常 10-60 秒；可用下面的命令观察："
say "  curl -sI https://${DOMAIN}/api/v1/health/live/"
