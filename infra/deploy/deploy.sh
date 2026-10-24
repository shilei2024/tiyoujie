#!/usr/bin/env bash
# 服务器端发布脚本：拉代码 → 构建镜像 → 备份数据库 → 迁移 → 起服务 → 健康检查。
# 任何一步失败都会把 API_IMAGE 还原到上一个镜像并重新拉起，避免“半新半旧”。
#
# 前置：setup-host.sh 已执行，apply-caddy.sh 已配置域名与证书。
# 用法（在 /opt/tiyoujie/repo 下以 root 执行）：
#   ./infra/deploy/deploy.sh --ref main
#   ./infra/deploy/deploy.sh --ref <commit-sha>
#   ./infra/deploy/deploy.sh --rollback            # 回到 .env.prod 里记录的上一版镜像
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_DIR}/.env.prod"
BACKUP_DIR="/opt/tiyoujie/backups"
REF="main"
ROLLBACK=0
SKIP_PULL=0
HEALTH_TIMEOUT=60

say() { printf '%s\n' "$1"; }
die() {
	printf '错误：%s\n' "$1" >&2
	exit 1
}

while [ $# -gt 0 ]; do
	case "$1" in
	--ref)
		REF="${2:-main}"
		shift 2
		;;
	--rollback)
		ROLLBACK=1
		shift
		;;
	--skip-pull)
		SKIP_PULL=1
		shift
		;;
	-h | --help)
		sed -n '2,10p' "$0"
		exit 0
		;;
	*) die "未知参数 $1" ;;
	esac
done

cd "$REPO_DIR"
[ -f "$ENV_FILE" ] || die "缺少 .env.prod，请先按 infra/deploy/env.prod.example 创建"

COMPOSE=(
	docker compose
	--project-directory "$REPO_DIR"
	--env-file "$ENV_FILE"
	-f compose.yaml
	-f infra/deploy/compose.prod.yaml
	-f infra/deploy/compose.caddy.yaml
	-p tiyoujie
)

env_value() {
	sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

set_env_value() {
	local key="$1" value="$2"
	if grep -q "^${key}=" "$ENV_FILE"; then
		sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
	else
		printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
	fi
}

say "== 0/6 配置自检 =="
# 基础编排的 dev 锚点要求该变量存在；未填写时与数据库口令保持一致。
if [ -z "$(env_value POSTGRES_PASSWORD)" ]; then
	set_env_value POSTGRES_PASSWORD "$(env_value DB_PASSWORD)"
fi
for key in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS DJANGO_CSRF_TRUSTED_ORIGINS \
	DB_NAME DB_USER DB_PASSWORD REDIS_PASSWORD REDIS_URL API_HOST_PORT; do
	[ -n "$(env_value "$key")" ] || die ".env.prod 缺少 ${key}"
done
case "$(env_value DJANGO_CSRF_TRUSTED_ORIGINS)" in
https://*) : ;;
*) die "DJANGO_CSRF_TRUSTED_ORIGINS 必须是 https:// 开头" ;;
esac
API_PORT="$(env_value API_HOST_PORT)"
PREVIOUS_IMAGE="$(env_value API_IMAGE)"

say "== 1/6 取代码 =="
if [ "$SKIP_PULL" -eq 1 ]; then
	say "跳过拉取，使用当前工作区。"
else
	git fetch --prune --depth=1 origin "$REF"
	git checkout -q --detach FETCH_HEAD
	say "已切换到 $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"
fi
SHA="$(git rev-parse --short HEAD)"
IMAGE="tiyoujie-api:${SHA}"

if [ "$ROLLBACK" -eq 1 ]; then
	LAST_FILE="${BACKUP_DIR}/last-image.txt"
	[ -s "$LAST_FILE" ] || die "没有找到上一版镜像记录：${LAST_FILE}"
	TARGET="$(cat "$LAST_FILE")"
	[ -n "$TARGET" ] || die "上一版镜像记录为空"
	say "回滚到 ${TARGET}"
	set_env_value API_IMAGE "$TARGET"
	"${COMPOSE[@]}" up -d --wait api worker beat
	exit 0
fi

say "== 2/6 构建镜像 ${IMAGE} =="
docker build -f infra/Dockerfile -t "$IMAGE" .
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
say "镜像摘要：${IMAGE_ID}"

say "== 3/6 激活新镜像并校验编排 =="
mkdir -p "$BACKUP_DIR"
if [ -n "$PREVIOUS_IMAGE" ] && [ "$PREVIOUS_IMAGE" != "$IMAGE" ]; then
	printf '%s\n' "$PREVIOUS_IMAGE" >"${BACKUP_DIR}/last-image.txt"
	say "已记录上一版镜像，可用于 --rollback：${PREVIOUS_IMAGE}"
fi
set_env_value API_IMAGE "$IMAGE"
"${COMPOSE[@]}" config --quiet || die "编排校验失败"

restore_previous() {
	if [ -n "$PREVIOUS_IMAGE" ]; then
		say "回滚 API_IMAGE → ${PREVIOUS_IMAGE}"
		set_env_value API_IMAGE "$PREVIOUS_IMAGE"
		"${COMPOSE[@]}" up -d --wait api worker beat || true
	fi
}
trap 'restore_previous' ERR

say "== 4/6 启动数据层并备份数据库 =="
"${COMPOSE[@]}" up -d --wait postgres redis
mkdir -p "$BACKUP_DIR"
if [ -n "$(docker compose -p tiyoujie ps --status running --format '{{.Service}}' 2>/dev/null | grep -x postgres || true)" ]; then
	STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
	# 备份只写本地磁盘，不打印任何连接串。
	if "${COMPOSE[@]}" exec -T postgres pg_dumpall -U postgres | gzip >"${BACKUP_DIR}/pre-deploy-${STAMP}.sql.gz"; then
		say "已备份：${BACKUP_DIR}/pre-deploy-${STAMP}.sql.gz"
	else
		die "数据库备份失败，停止发布（不覆盖已有数据）"
	fi
fi

say "== 5/6 迁移数据库 =="
"${COMPOSE[@]}" run --rm --no-deps api python manage.py migrate --noinput

say "== 6/6 启动应用并健康检查 =="
"${COMPOSE[@]}" up -d --wait api worker beat

for _ in $(seq "$HEALTH_TIMEOUT"); do
	if curl -fsS "http://127.0.0.1:${API_PORT}/api/v1/health/ready/" >/dev/null 2>&1; then
		trap - ERR
		say ""
		say "发布成功：${IMAGE}"
		say "  镜像摘要：${IMAGE_ID}"
		say "  本地就绪探针：http://127.0.0.1:${API_PORT}/api/v1/health/ready/"
		DOMAIN="$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f1)"
		say "  对外域名：https://${DOMAIN}/api/v1/health/live/"
		say "  回滚命令：./infra/deploy/deploy.sh --rollback"
		exit 0
	fi
	sleep 1
done

trap - ERR
restore_previous
die "健康检查 ${HEALTH_TIMEOUT}s 未通过，已触发回滚"
