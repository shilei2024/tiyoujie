# 上线手册：腾讯云主机 + tiyoujie.pxcore.com.cn

日期：2026-10-24。目标：把「人工错题 → 题单 → 复习 → 导出」这条闭环部署到真实域名，并保留可回滚路径。

前置阅读：[域名与 TLS](tls-and-domain.md)、[Phase 7 部署手册](phase-7-deployment.md)。

## 0. 需要人为提供的东西

| 项 | 谁提供 | 用途 | 缺失后果 |
| --- | --- | --- | --- |
| SSH 登录方式（密码或把公钥加入 `~/.ssh/authorized_keys`） | 你 | 在主机执行初始化与发布 | 无法部署 |
| DNS A 记录 `tiyoujie` → 服务器 IP | 你在 DNSPod 添加 | Caddy 申请证书的前提 | 证书申请失败 |
| 微信小程序 AppSecret | 微信公众平台 → 开发设置 | 服务端换取会话 | 小程序无法登录 |
| 隐私政策链接与监护人告知版本号 | 你确认 | 合规文案与 `GUARDIAN_NOTICE_VERSION` | 不得对外发布 |
| 数据保留期与备份保留期 | 你确认 | 备份策略 | 保留策略不明确 |

平台 AI/OCR 与题库推荐**不在本次范围**，相关开关保持关闭。

## 1. 主机初始化（一次性）

以 root 登录服务器，把仓库放到 `/opt/tiyoujie/repo`：

```bash
mkdir -p /opt/tiyoujie/repo && cd /opt/tiyoujie/repo
git clone https://github.com/<你的账号>/tiyoujie.git .
sudo bash infra/deploy/setup-host.sh --dry-run   # 先看会做什么
sudo bash infra/deploy/setup-host.sh --firewall
```

`setup-host.sh` 做的事情：装 Docker/Compose、设时区为 Asia/Shanghai、内存 < 4GB 时建 2GB swap、写日志轮转（单文件 10MB × 5）、建 `/opt/tiyoujie/backups`、按需放行 22/80/443。

若拉取 Docker 官方脚本缓慢，可换镜像源：

```bash
sudo bash infra/deploy/setup-host.sh --docker-script-url https://mirrors.aliyun.com/docker-ce/linux/ubuntu/...
# 更稳妥的做法是按阿里云文档手动 apt 安装 docker-ce + docker-compose-plugin
```

要求：`docker compose version` ≥ 2.24（编排使用了 `!override` 合并端口）。

## 2. 写生产配置

```bash
cd /opt/tiyoujie/repo
cp infra/deploy/env.prod.example .env.prod
chmod 600 .env.prod
openssl rand -hex 32   # DJANGO_SECRET_KEY
openssl rand -hex 24   # DB_PASSWORD
openssl rand -hex 24   # REDIS_PASSWORD
```

`infra/deploy/env.prod.example` 逐项说明：

| 变量 | 填什么 |
| --- | --- |
| `DJANGO_SECRET_KEY` | 上面生成的 64 位十六进制；**不要**与数据库口令相同 |
| `DJANGO_ALLOWED_HOSTS` | `tiyoujie.pxcore.com.cn`（只写域名，逗号分隔） |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://tiyoujie.pxcore.com.cn`（必须 https） |
| `DB_PASSWORD` | 数据库口令；`POSTGRES_PASSWORD` 留空时发布脚本会自动同值填充 |
| `REDIS_PASSWORD` / `REDIS_URL` | 口令一致；`REDIS_URL` 必须带口令或 `rediss://`，否则进程拒绝启动 |
| `API_HOST_PORT` | 默认 `18010`，只绑 `127.0.0.1` |
| `WECHAT_APP_ID` / `WECHAT_APP_SECRET` | 先填 AppID；AppSecret 拿到后补 |
| `OCR_OUTBOUND_ENABLED` / `AI_ANALYSIS_ENABLED` / `PLATFORM_AI_ENABLED` | 保持 `0` |
| `API_IMAGE` | 首次可留占位，`deploy.sh` 会自动改成当前提交对应的镜像 |

`.env.prod` 已在 `.gitignore` 中，不要提交、不要贴到聊天里。

## 3. 首次发布

```bash
cd /opt/tiyoujie/repo
sudo bash infra/deploy/deploy.sh --ref main
```

脚本顺序（任一步失败都会把 `API_IMAGE` 还原并重新拉起上一个镜像）：

1. 校验 `.env.prod` 必填项与 https 来源；
2. `git fetch` 并切到目标提交；
3. `docker build` 出 `tiyoujie-api:<sha>` 并打印镜像摘要；
4. 启动 PostgreSQL/Redis，**先 `pg_dumpall` 备份**（首次为空库，跳过）；
5. `manage.py migrate --noinput`；
6. 启动 api/worker/beat，轮询 `127.0.0.1:18010/api/v1/health/ready/` 最多 60 秒。

成功后会打印镜像摘要、健康检查地址与回滚命令。

## 4. 接入域名

```bash
sudo ./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010 --dry-run
sudo ./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010
curl -fsS https://tiyoujie.pxcore.com.cn/api/v1/health/live/
curl -fsS https://tiyoujie.pxcore.com.cn/api/v1/health/ready/
```

`ready` 返回 503 时先看数据库/Redis 与迁移一致性，**不要用重启掩盖**。

## 5. 小程序侧

```bash
py -3.12 scripts/wechat.py build --api-base https://tiyoujie.pxcore.com.cn
```

产物在 `frontend/dist/build/mp-weixin`，用微信开发者工具导入，上传体验版。然后：

1. 后台把 `https://tiyoujie.pxcore.com.cn` 加入 request 合法域名（不带路径/端口）；
2. 真机依次验证：登录 → 建家庭/孩子 → 上传图片并确认题干 → 错题列表 → 生成题单 → 作答 → 今日复习 → 导出。

## 6. 回滚

```bash
cd /opt/tiyoujie/repo
sudo bash infra/deploy/deploy.sh --rollback     # 回到 /opt/tiyoujie/backups/last-image.txt 记录的上一版
```

数据库迁移**不会**自动回退。若新版本已执行破坏性迁移，先恢复发布前的备份：

```bash
ls -lt /opt/tiyoujie/backups/pre-deploy-*.sql.gz | head
gunzip -c /opt/tiyoujie/backups/pre-deploy-<时间>.sql.gz | \
  docker compose -p tiyoujie exec -T postgres psql -U postgres
```

## 7. 备份

发布前自动备份只覆盖「发布这一刻」。日常备份建议加 cron（每天 03:10，保留 14 天）：

```cron
10 3 * * * cd /opt/tiyoujie/repo && docker compose -p tiyoujie exec -T postgres pg_dumpall -U postgres | gzip > /opt/tiyoujie/backups/daily-$(date +\%Y\%m\%d).sql.gz && find /opt/tiyoujie/backups -name 'daily-*.sql.gz' -mtime +14 -delete
```

`private` 卷（孩子图片）不在数据库里，需一并备份：

```cron
20 3 * * * docker run --rm -v tiyoujie_private_prod:/data:ro -v /opt/tiyoujie/backups:/out alpine tar czf /out/media-$(date +\%Y\%m\%d).tar.gz -C /data .
```

恢复演练方法见 [本地开发手册](../development/local-development.md) 与 `artifacts/phase7_restore_drill.py`。

## 8. 上线后每天该看什么

| 检查 | 命令 | 正常表现 |
| --- | --- | --- |
| 存活 | `curl -fsS https://tiyoujie.pxcore.com.cn/api/v1/health/live/` | `{"status":"ok"}` |
| 就绪 | `curl -fsS https://tiyoujie.pxcore.com.cn/api/v1/health/ready/` | `{"status":"ready"}` |
| 磁盘 | `df -h /` | 使用率 < 80% |
| 容器 | `docker compose -p tiyoujie ps` | api/worker/beat/postgres/redis 均 Up |
| 证书 | `echo \| openssl s_client -connect tiyoujie.pxcore.com.cn:443 -servername tiyoujie.pxcore.com.cn 2>/dev/null \| openssl x509 -noout -enddate` | 剩余 > 30 天 |
| 日志 | `docker compose -p tiyoujie logs --tail 100 api` | 无成片 500 与堆栈 |

## 9. 当前验证状态（不要夸大为「已验证上线」）

| 项 | 状态 |
| --- | --- |
| 生产编排合并、端口只绑回环、nginx 不启动 | 本机 `docker compose config` 实测 PASS |
| `manage.py check --deploy`（prod 设置） | PASS，0 issue |
| Caddy 站点块语法与运行时行为 | 本机用真实 Caddy 2.10 + 内部证书演练 PASS（HSTS、去 Server 头、404、9MB 上限、无 301 循环） |
| Caddy → 应用 → 数据库全链路 | 本机演练 PASS；**真实主机未执行** |
| Let's Encrypt 真实签发 | **未执行**（需要 DNS 生效 + 80 端口放行） |
| 微信真机联网 | **未执行**（需要 AppSecret 与合法域名配置） |

真实主机上的每一步执行后，请把输出贴回，或让我远程执行后再更新本表。
