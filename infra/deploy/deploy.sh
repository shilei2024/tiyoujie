#!/usr/bin/env bash
# 服务器端发布脚本：拉代码 → 构建镜像 → 备份数据库 → 迁移 → 起服务 → 健康检查。
# 任何一步失败都会把 API_IMAGE 还原到上一个镜像并重新拉起，避免“半新半旧”。
#
# 前置：setup-host.sh 已执行；首次上线需额外跑 apply-caddy.sh 配置域名与证书
#（或给本脚本加 --apply-caddy，发布成功后自动执行）。
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
APPLY_CADDY=0
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
	--apply-caddy)
		APPLY_CADDY=1
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
BIND_IP="$(env_value API_BIND_IP)"
[ -n "$BIND_IP" ] || {
	BIND_IP="172.17.0.1"
	set_env_value API_BIND_IP "$BIND_IP"
}
# API 只绑 docker0，由主机既有 Caddy 容器经 host.docker.internal 回源。
# docker0 地址会随 Docker 重建而变，变了必须显式修正，否则对公网不可达却看不出原因。
DOCKER0_IP="$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)"
[ -n "$DOCKER0_IP" ] || die "找不到 docker0 网卡，无法确定 API 绑定地址"
[ "$DOCKER0_IP" = "$BIND_IP" ] ||
	die "API_BIND_IP=${BIND_IP} 与当前 docker0=${DOCKER0_IP} 不一致；请执行 sed -i 's|^API_BIND_IP=.*|API_BIND_IP=${DOCKER0_IP}|' .env.prod 后重试"
DOMAIN="$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f1)"
say "API 绑定：${BIND_IP}:${API_PORT}（仅 docker0，公网不可达），对外域名：${DOMAIN}"
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
	"${COMPOSE[@]}" up -d --wait --no-build api worker beat
	exit 0
fi

say "== 2/6 构建镜像 ${IMAGE} =="
# 受限网络下用镜像源构建；变量为空时保持官方源，不影响 CI 与其它环境。
BUILD_ARGS=()
for key in PYPI_INDEX PYPI_FILES_HOST; do
	value="$(env_value "$key")"
	if [ -n "$value" ]; then
		BUILD_ARGS+=(--build-arg "${key}=${value}")
	fi
done
[ ${#BUILD_ARGS[@]} -eq 0 ] ||
	say "使用镜像源构建：${BUILD_ARGS[*]}"
docker build ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} -f infra/Dockerfile -t "$IMAGE" .
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
	if [ -z "$PREVIOUS_IMAGE" ]; then
		return 0
	fi
	if ! docker image inspect "$PREVIOUS_IMAGE" >/dev/null 2>&1; then
		say "上一版镜像 ${PREVIOUS_IMAGE} 不存在，跳过自动回滚（需人工处理）"
		return 0
	fi
	say "回滚 API_IMAGE → ${PREVIOUS_IMAGE}"
	set_env_value API_IMAGE "$PREVIOUS_IMAGE"
	"${COMPOSE[@]}" up -d --wait --no-build api worker beat || true
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
"${COMPOSE[@]}" up -d --wait --no-build api worker beat

for _ in $(seq "$HEALTH_TIMEOUT"); do
	if curl -fsS -H "Host: ${DOMAIN}" -H "X-Forwarded-Proto: https" \
		"http://${BIND_IP}:${API_PORT}/api/v1/health/ready/" >/dev/null 2>&1; then
		trap - ERR
		say ""
		say "发布成功：${IMAGE}"
		say "  镜像摘要：${IMAGE_ID}"
		say "  就绪探针：http://${BIND_IP}:${API_PORT}/api/v1/health/ready/"
		say "  对外域名：https://${DOMAIN}/api/v1/health/live/"
		say "  回滚命令：./infra/deploy/deploy.sh --rollback"
		if [ "$APPLY_CADDY" -eq 1 ]; then
			say ""
			say "== 附加：把站点块并入主机 Caddy =="
			"${REPO_DIR}/infra/deploy/apply-caddy.sh" \
				--domain "$(env_value DJANGO_ALLOWED_HOSTS | cut -d, -f1)" \
				--upstream "$API_PORT"
		fi
		exit 0
	fi
	sleep 1
done

trap - ERR
restore_previous
die "健康检查 ${HEALTH_TIMEOUT}s 未通过，已触发回滚"
