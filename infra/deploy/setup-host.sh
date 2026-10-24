#!/usr/bin/env bash
# 腾讯云 Ubuntu 24.04 主机初始化：Docker、日志上限、swap、时区、目录。
#
# 默认动作只做“可回退的安装与配置”，不会改防火墙状态；
# 加 --firewall 才会启用 ufw（会先放行 SSH 端口，避免把自己关在门外）。
#
# 用法（在服务器上以 root 执行）：
#   bash setup-host.sh --dry-run
#   bash setup-host.sh
#   bash setup-host.sh --firewall --ssh-port 22
set -euo pipefail

APP_DIR="/opt/tiyoujie"
SSH_PORT="22"
FIREWALL=0
DRY_RUN=0
DOCKER_SCRIPT_URL="https://get.docker.com"

say() { printf '%s\n' "$1"; }
die() {
	printf '错误：%s\n' "$1" >&2
	exit 1
}
run() {
	if [ "$DRY_RUN" -eq 1 ]; then
		printf '[预演] %s\n' "$*"
	else
		"$@"
	fi
}

while [ $# -gt 0 ]; do
	case "$1" in
	--ssh-port)
		SSH_PORT="${2:-22}"
		shift 2
		;;
	--firewall)
		FIREWALL=1
		shift
		;;
	--dry-run)
		DRY_RUN=1
		shift
		;;
	--docker-script-url)
		DOCKER_SCRIPT_URL="${2:-}"
		shift 2
		;;
	-h | --help)
		sed -n '2,12p' "$0"
		exit 0
		;;
	*) die "未知参数 $1" ;;
	esac
done

[ "$(id -u)" -eq 0 ] || die "请用 root 或 sudo 执行"
[ -r /etc/os-release ] || die "无法识别系统版本"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
ubuntu:24.04 | ubuntu:22.04 | debian:12) : ;;
*) say "提示：当前系统 ${PRETTY_NAME:-未知} 未在验证范围内，脚本会继续但请自行确认 apt 源可用。" ;;
esac

say "== 1/6 基础软件包 =="
run apt-get update -qq
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
	ca-certificates curl gnupg git ufw openssl jq cron

say "== 2/6 时区 =="
run timedatectl set-timezone Asia/Shanghai || say "跳过时区设置"

say "== 3/6 swap（内存小于 4GB 时创建 2GB） =="
MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "$(awk '/SwapTotal/ {print $2}' /proc/meminfo)" -gt 0 ]; then
	say "已有 swap，跳过。"
elif [ "$MEM_KB" -lt 4194304 ]; then
	if [ -f /swapfile ]; then
		say "/swapfile 已存在，跳过创建。"
	else
		run fallocate -l 2G /swapfile
		run chmod 600 /swapfile
		run mkswap /swapfile
		run swapon /swapfile
		if ! grep -q '^/swapfile ' /etc/fstab; then
			if [ "$DRY_RUN" -eq 1 ]; then
				say "[预演] 追加 swap 到 /etc/fstab"
			else
				echo '/swapfile none swap sw 0 0' >>/etc/fstab
			fi
		fi
	fi
else
	say "内存充足，跳过 swap。"
fi

say "== 4/6 Docker =="
if command -v docker >/dev/null 2>&1; then
	say "Docker 已安装：$(docker --version)"
else
	[ -n "$DOCKER_SCRIPT_URL" ] || die "未提供 Docker 安装脚本地址"
	TMP_SCRIPT="$(mktemp)"
	run curl -fsSL "$DOCKER_SCRIPT_URL" -o "$TMP_SCRIPT"
	run sh "$TMP_SCRIPT"
	rm -f "$TMP_SCRIPT"
fi
run systemctl enable --now docker

mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
	say "写入 /etc/docker/daemon.json（日志轮转，防止磁盘被写满）"
	if [ "$DRY_RUN" -eq 1 ]; then
		say "[预演] 写入 daemon.json"
	else
		cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "live-restore": true
}
JSON
		systemctl restart docker
	fi
else
	say "/etc/docker/daemon.json 已存在，保持不动。"
fi

say "== 5/6 目录 =="
run mkdir -p "$APP_DIR"/{backups,repo}
run chmod 700 "$APP_DIR/backups"

say "== 6/6 防火墙 =="
if [ "$FIREWALL" -eq 1 ]; then
	# 不执行 ufw reset：主机上可能已有其它站点的规则，只做增量放行。
	run ufw default deny incoming
	run ufw default allow outgoing
	run ufw allow "${SSH_PORT}/tcp"
	run ufw allow 80/tcp
	run ufw allow 443/tcp
	run ufw --force enable
	run ufw status verbose
else
	say "未改动防火墙。放行命令（腾讯云还需在控制台安全组同样放行）："
	say "  ufw allow ${SSH_PORT}/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable"
fi

say ""
say "== 结果 =="
docker --version || true
docker compose version || true
COMPOSE_VERSION="$(docker compose version --short 2>/dev/null || echo 0)"
if [ "${COMPOSE_VERSION%%.*}" -lt 2 ]; then
	die "Compose 版本过低，需要 >= 2.24（本例使用 !override 合并端口）"
fi
say "下一步：把代码放到 ${APP_DIR}/repo，再执行 deploy.sh。"
