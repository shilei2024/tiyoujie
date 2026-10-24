# Phase 7 部署、回滚与故障手册

日期：2026-10-24。**状态：脚本与编排已就绪，但未在真实主机、真实域名或真实微信环境执行。** 本文命令以 Linux + Docker Compose v2 为前提；Windows 本地开发不使用生产编排。

## 1. 上线前必须由责任人确认

| 项 | 为什么必须 | 当前状态 |
| --- | --- | --- |
| 域名与 TLS 证书 | 微信小程序强制 HTTPS，且 CSRF/HSTS 依赖真实域名 | 未提供 |
| 服务器与磁盘 | 容器、数据库、备份空间与内存配额 | 未提供 |
| 微信 AppSecret | 服务端换取会话；缺失时登录不可用 | 未提供（AppID 已配置） |
| 隐私政策与监护人告知版本 | `GUARDIAN_NOTICE_VERSION` 与合规文本一致 | 未确认 |
| OCR/AI 供应商条款与价格 | 平台付费能力 fail closed 的前置条件 | 未确认（默认关闭） |
| 数据保留与备份保留期 | 决定备份频率与删除策略 | 未确认 |

任何一项缺失时，平台 AI/OCR 保持关闭，只能上线“人工错题 + 复习 + 导出”的范围；不能宣称具备自动识别与智能分析。

## 2. 构建与固定镜像

```bash
docker build -f infra/Dockerfile -t tiyoujie-api:<git-sha> .
docker save tiyoujie-api:<git-sha> | sha256sum      # 记录摘要
# 推送到私有仓库后，用 digest 写回 .env.prod 的 API_IMAGE
```

要求：CI 全量测试、`pip-audit`、`npm audit`、前端双端构建全部通过后才允许构建用于部署的镜像。镜像 digest 与源码 commit 必须成对记录在发布报告中。

## 3. 配置秘密

```bash
cp infra/deploy/env.prod.example .env.prod
chmod 600 .env.prod
openssl rand -base64 48   # DJANGO_SECRET_KEY
openssl rand -base64 32   # DB_PASSWORD / REDIS_PASSWORD
```

- `DJANGO_ALLOWED_HOSTS` 只写真实 API 域名；`DJANGO_CSRF_TRUSTED_ORIGINS` 必须是 `https://`。
- `REDIS_URL` 必须带密码或使用 `rediss://`，否则进程拒绝启动。
- `CREDENTIAL_KEYS_JSON` 与 `CREDENTIAL_ACTIVE_KEY_VERSION` 仅在启用 BYOK 时填写；主密钥与 Django secret 分开保管。
- `.env.prod`、TLS 私钥、备份文件不得进入仓库或镜像。

静态校验（不连接任何外部数据库）：

```bash
docker compose -f compose.yaml -f infra/deploy/compose.prod.yaml --env-file .env.prod config --quiet
docker compose ... run --rm api python manage.py check --deploy
```

## 4. 迁移与首次启动

```bash
# 1) 只启动数据层
docker compose -f compose.yaml -f infra/deploy/compose.prod.yaml --env-file .env.prod up -d postgres redis

# 2) 显式迁移，失败立即停止，不要“重启大法”
docker compose ... run --rm api python manage.py migrate --noinput

# 3) 启动应用与代理
docker compose ... up -d api worker beat nginx

# 4) 验证
curl -fsS https://api.example.com/api/v1/health/live/
curl -fsS https://api.example.com/api/v1/health/ready/
docker compose ... exec api python manage.py queue_probe
```

`ready` 返回 503 时先看数据库/Redis 与迁移一致性，不要通过重启掩盖。首次启动不自动灌入任何业务数据或管理员账号；管理员用 `createsuperuser` 交互创建。

## 5. 微信小程序配置

1. 小程序后台把 `https://api.example.com` 加入 request 合法域名；不关闭域名校验。
2. 前端构建使用 `py -3.12 scripts/wechat.py build --api-base https://api.example.com`，再由平台负责人上传体验版。
3. 服务端设置 `WECHAT_APP_ID` 与 `WECHAT_APP_SECRET`；AppSecret 只存在于后端环境变量。
4. 真机验证：登录、创建家庭/孩子、上传图片、确认题干、题单作答、复习、导出（家长端 H5）。

## 6. 备份

本地演练与运维入口：`py -3.12 scripts/backup.py`（生产主机请用等价命令并写入 cron）。

```bash
# 每日 02:30，保留 7 份；周末另存 4 周；异机加密复制
30 2 * * * cd /srv/tiyoujie && docker exec -e PGPASSWORD="$DB_PASSWORD" tiyoujie-postgres-1 \
  pg_dump -U postgres -d tiyoujie --format=custom > /backup/db-$(date +\%F).dump
```

要求：数据库 dump、私有存储归档、清单与 SHA-256 必须同一批生成；备份加密后异机保存；保留期与删除策略由责任人确认。备份文件包含儿童学习数据，禁止放入公开对象存储。

## 7. 恢复

顺序固定，禁止直接覆盖生产：

1. 在**独立** Compose 项目/主机创建新数据库与新存储卷，停 Worker/Beat、关闭供应商出口。
2. 恢复 DB 与文件，逐一比对清单与 SHA-256。
3. 校验：题目与图片关联、题单快照、作答与复习计划、题库许可状态、两个家庭之间的越权抽样。
4. 重新执行删除清单：已注销账号、已删除题单/错题、过期导出票据不得恢复可读。
5. 检查预算/配额账本与 outbox：不自动重放已付费或未知费用的任务。
6. 记录耗时与数据量，确认后才允许切换流量。

本地演练结果见 [Phase 7 报告](../acceptance/phase-7-report.md) 与 `artifacts/phase7-restore-report.json`。

## 8. 回滚

- 只回滚镜像：`API_IMAGE` 指向上一版 digest 后 `up -d api worker beat`。前提是数据库结构向后兼容。
- 迁移不可逆时：不执行 `migrate <app> <old>` 猜测回退；用备份恢复到新数据库，验证后切换连接串。
- 回滚期间保持供应商外发关闭，避免重复计费。
- 每次发布记录：旧/新镜像 digest、迁移列表、备份编号、发布前后行数与健康状态。

## 9. 密钥与凭证轮换

| 对象 | 操作 | 注意 |
| --- | --- | --- |
| BYOK 主密钥 | `manage.py rotate_credential_key --new-key-version ...` | 旧版本保留至全部凭证重加密完成；不输出明文 |
| 微信 AppSecret | 平台后台重置 → 更新 `.env.prod` → 重启 api/worker | 旧 secret 立即失效，登录会短暂失败 |
| Django SECRET_KEY | 更换后所有会话与签名链接失效 | 导出票据、邀请令牌需重新生成 |
| DB/Redis 密码 | 先改服务端再滚动重启 | 期间 `ready` 会 503，属预期 |

## 10. 故障处置

| 症状 | 处置 |
| --- | --- |
| `ready` 503 | 检查 DB/Redis 连通与迁移；不看缓存指标代替 |
| 队列积压 | 看 Worker 日志与供应商限流；不批量盲目重试付费任务 |
| 供应商超时/未知费用 | 保留预占、标记待对账、关闭平台外发；不影响人工功能 |
| 磁盘不足 | 优先清理过期导出票据与孤儿对象；禁止删除数据库卷 |
| 疑似数据越权 | 立即停用相关账号会话、保留审计记录、按威胁模型排查 |
| 导出异常 | 检查票据过期（10 分钟）与对象删除状态；`410` 属正常拒绝 |

## 11. 明确未验证

- 真实 TLS 握手、HSTS 预加载、证书自动续期。
- 真实微信登录、真机、上传体验版与审核。
- 多实例并发、数据库主从、对象存储与跨机备份。
- 真实供应商调用与费用对账。

以上未验证项在发布报告中保持 BLOCKED / NOT TESTED，不能用本地测试结果替代。
