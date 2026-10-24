# Phase 9：真机部署上线记录

日期：2026-10-24。本文只记录**在目标主机上实际执行过**的动作与结果，
未执行的一律标注 NOT TESTED，不用推演代替证据。

站点：**https://tiyoujie.pxcore.com.cn**（Let's Encrypt 证书已签发）

---

## 1. 主机实测环境

| 项 | 实测值 |
| --- | --- |
| 主机名 / 系统 | `VM-0-17-ubuntu` / Ubuntu 24.04.3 LTS，内核 6.8.0-100 |
| 规格 | 4 vCPU，3.7 GiB 内存，69 GiB 磁盘（用 45 GiB，剩 22 GiB） |
| 已运行服务 | `mindfulpenpal-ai-production-caddy-1`（占 80/443）、`mindfulpenpal-*` 共 9 个容器、`tongyan-api`、宿主机 gunicorn:8000（Flask 站点） |
| 内存现状 | 部署前 available 1.5 GiB，swap 1.9 GiB 已用 1.4 GiB |
| Docker | 29.2.1，Compose v5.0.2；`/etc/docker/daemon.json` 已配腾讯云镜像与阿里 DNS |
| 到 PyPI 的连通性 | pypi.org 索引 47 MB 仅约 50 KB/s；`files.pythonhosted.org` 直接 ReadTimeoutError |

第二行决定了两个关键决策：**不抢 80/443**，以及**构建必须走镜像源**。

---

## 2. 最终拓扑

```
用户/小程序
    │ HTTPS
    ▼
主机 Caddy（容器 mindfulpenpal-ai-production-caddy-1）
    │ 站点块 tiyoujie.pxcore.com.cn → host.docker.internal:18010
    ▼
docker0 网关 172.17.0.1:18010（只绑 docker0，公网 IP 不监听）
    ▼
容器 tiyoujie-api-1 (gunicorn 2 worker) ──┬── tiyoujie-postgres-1
                                          ├── tiyoujie-redis-1
                                          ├── tiyoujie-worker-1
                                          └── tiyoujie-beat-1
```

为什么绑 docker0 而不是加进 Caddy 所在网络：该网络里 `tongyan-api` 已经占用
DNS 别名 `api`，本项目加入会导致 `api` 解析到两个容器，请求间歇性打到错误的服务。

Caddy 配置是单文件 bind mount：
`/opt/mytoolbox/services/generation-service/deploy/Caddyfile.production` → `/etc/caddy/Caddyfile`。
本项目只追加 `# >>> tiyoujie … >>>` 包裹的一个站点块，其余站点块字节不变。

---

## 3. 执行顺序与实际结果

| 步骤 | 动作 | 结果 |
| --- | --- | --- |
| 1 | 新增 swap `/swapfile2` 2 GiB（不重启 Docker），`vm.swappiness=10` | PASS：swap 4.0 GiB，可用 2.65 GiB |
| 2 | 代码投递到 `/opt/tiyoujie/repo`（GitHub 直连超时，改用 `git bundle` + scp） | PASS，HEAD `effa3b9` |
| 3 | 生成 `.env.prod`（600 权限，全部随机口令，未打印任何值） | PASS，22 个变量 |
| 4 | `docker build`（清华镜像源） | PASS，镜像 `tiyoujie-api:be958da`，542 MB |
| 5 | 建库 + 迁移 | PASS：38 迁移 / 55 表 / 18 触发器 |
| 6 | 起 api / worker / beat，健康检查 | PASS：5 容器全部 healthy |
| 7 | 把站点块并入主机 Caddy | PASS：备份 → 校验 → 生效 |
| 8 | Let's Encrypt 自动签发 | PASS：CN=tiyoujie.pxcore.com.cn，签发者 YE2，2026-10-24 ～ 2027-01-22 |
| 9 | `manage.py check --deploy`（真机真变量） | PASS：0 issue |

第一次 `deploy.sh` 因下面第 4 项缺陷失败并自动回滚；修复后重跑一次成功。
最终镜像摘要：`sha256:23390b22e1c413549d23c50a071e449a9fe20e79c41de744b8e24bc17075992e`

---

## 4. 真机暴露并已修复的五个缺陷

前四个在本地测试与 CI 中全部通过，只有真实环境才会暴露。

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | `docker build` 卡在 `pip install uv` 后失败 | 主机到 PyPI 只有 ~50 KB/s，文件下载直接读超时 | Dockerfile 增加 `PYPI_INDEX` / `PYPI_FILES_HOST` 构建参数；构建期把 `uv.lock` 里的 290 个下载地址替换为镜像主机（镜像逐字节一致，sha256 校验仍生效） |
| 2 | 迁移报 `password authentication failed for user "tiyoujie"` | `infra/postgres/dev.sql` 把角色/库名写死成 `tiyoujie_dev`，生产角色根本不存在；PostgreSQL 对不存在的角色也报“密码错误”（防用户名枚举） | 新增参数化 `infra/postgres/prod.sql`，角色与库名取自 `.env.prod` |
| 3 | 迁移失败后 compose 又去构建一个不存在的 tag，再次撞 PyPI | `deploy.sh` 的 ERR 回滚把 `API_IMAGE` 退回旧 tag，而 compose `up` 会自动构建缺失镜像且不带构建参数 | 回滚前校验镜像存在；`up` 一律 `--no-build`；`build.args` 也写进编排 |
| 4 | api 容器永远 unhealthy | 生产 `ALLOWED_HOSTS` 只有真实域名，探针以 `127.0.0.1` 作 Host 被判 400；即便放开 Host，`SECURE_SSL_REDIRECT` 又会把明文探针 301 掉 | healthcheck 与 `deploy.sh` 探针都带真实 `Host` 与 `X-Forwarded-Proto: https`（实测无头 400、带头 200） |
| 5 | 配置写入并“校验通过”，但站点不生效、TLS 报 internal error | `install` 替换了 Caddyfile，产生新 inode；Docker 单文件 bind mount 仍绑旧 inode。容器内看不到新内容，`caddy reload` 返回 `config is unchanged` | 改为 `cat > file` 原地写入保留 inode；写后比对容器内与宿主文件 md5，不一致时明确报错或按 `--restart-container` 重启 |

第 5 项最隐蔽：宿主文件正确、临时容器校验通过、reload 也“成功”，只有签名证书拿不到时才会发现。

另外修正一处会在上线后爆发的安全问题：限流身份原先取 `REMOTE_ADDR`，
代理之后所有人都是 `172.17.0.1`，等于共用一个限流桶——正常用户会被他人拖慢，
攻击者打满一个桶即可让全体用户无法登录。现改为仅在部署环境信任
`X-Forwarded-For` 且只取最后一跳。

### 4.1 运营阶段暴露的两个流程缺陷（不影响线上功能，但会骗过验收）

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| 6 | `deploy.sh --ref main` 打印“发布成功”，但服务器上的版本号没变，新提交的脚本找不到 | 此前因 GitHub 直连超时，服务器 `origin` 被改成离线 `git bundle` 文件。`git fetch` 读的还是那个静态文件，永远返回旧提交 | 服务器 `origin` 改回 `https://github.com/shilei2024/tiyoujie.git`（实测可直连）；`deploy.sh` 检测到 `origin` 是本地路径时打印警告与该文件修改时间，并在每次拉取后打印“代码来源” |
| 7 | 新增的后端测试“没生效”：测试数不变，改动完全没被测到 | `scripts/project.py test` 跑在镜像里，`test` 子命令不会重建镜像，所以验证的是上一次构建的旧代码 | `test` 子命令先执行 `compose build api` 再跑用例；CI 本来就是 build→test，语义一致 |

第 7 项最危险：它让“全绿”失去意义。发现方式是新写的 3 个用例既没有让测试数变化、也没有报错。

---

## 5. 线上验收（全部真实执行）

| 检查 | 结果 |
| --- | --- |
| `GET /api/v1/health/live/` | `{"status":"ok","service":"tiyoujie","ai":"disabled"}` |
| `GET /api/v1/auth/capabilities/` | `dev_login_available=false`（生产已关测试登录）、`wechat_configured=false`（待填 AppSecret） |
| HTTP → HTTPS | 308 跳转到 `https://tiyoujie.pxcore.com.cn/...` |
| 安全响应头 | HSTS 1 年含子域、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`、无 `Server` 头 |
| 证书链 | 浏览器/curl 默认 CA 校验通过（无需 `-k`） |
| 未知路径 | 404 |
| 10 MB 请求体 | 413（边缘拒绝，未进入应用） |
| 其他站点回归 | `api.pxcore.com.cn` 404（与部署前一致）、`mindfulpenpal.com` 200、`www.mindfulpenpal.com` 301 |
| 容器资源 | api 131 MB / worker 104 MB / beat 73 MB / pg 54 MB / redis 7 MB，合计约 369 MB |
| `check --deploy` | 0 issue |

---

## 6. 仍未完成（阻断项）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 小程序 AppSecret | **BLOCKED** | 未提供。生产已关闭 dev-login，微信登录是唯一入口，缺失时 `/auth/wechat-login/` 返回 503 |
| 小程序「服务器域名」白名单 | **BLOCKED** | 需在微信后台把 `https://tiyoujie.pxcore.com.cn` 加入 request 合法域名，否则真机请求被拦 |
| 小程序体验版/正式版上传 | **NOT TESTED** | 需 AppSecret 到位后由开发者工具上传并真机验证 |
| 真机端到端登录 | **NOT TESTED** | 依赖上面两项 |
| 隐私政策与监护人告知 | **BLOCKED** | 版本 `2026-10-v1` 已内置；[文本已按实际数据流备好](../legal/privacy-notice.md)，仅缺运营主体名称/联系邮箱/生效日期 |
| 平台 AI / OCR | 保持关闭 | 无合同、凭证与授权样本 |
| 授权题库 | 保持关闭 | 无授权证明与审核人 |
| 异机 / 生产规模备份恢复 | **NOT TESTED** | 本机隔离演练已通过（Phase 7） |

在上表第一、二项完成前，**可对外提供的是人工范围**：家庭与孩子、图片上传与人工核对、
错题、题单、作答、间隔复习、趋势、导出、删除与注销。

---

## 7. 运维命令速查

```bash
# 发布（服务器上，root）
cd /opt/tiyoujie/repo && ./infra/deploy/deploy.sh --ref main       # 从 GitHub 拉取并发布
cd /opt/tiyoujie/repo && ./infra/deploy/deploy.sh --skip-pull      # 代码已投放时

# AppSecret 写入后校验（真向微信换 token，失败按 errcode 给原因）
cd /opt/tiyoujie/repo && bash infra/deploy/verify-wechat.sh

# 回滚到上一版镜像
./infra/deploy/deploy.sh --rollback

# 站点块变更（会自动备份、校验、失败回滚）
./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010
./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --remove     # 下线

# 查看状态
docker compose -p tiyoujie --env-file .env.prod -f compose.yaml \
  -f infra/deploy/compose.prod.yaml ps
docker logs tiyoujie-api-1 --tail 50
docker logs mindfulpenpal-ai-production-caddy-1 --tail 50

# 部署日志与备份
/opt/tiyoujie/deploy.log
/opt/tiyoujie/backups/          # 部署前数据库转储
/opt/tiyoujie/backups/caddy/    # 每次改 Caddyfile 前的快照
```

**注意**：`deploy.sh` 不要直接挂在 SSH 会话里跑，连接断开会带走进程；
用 `setsid bash -c '… > /opt/tiyoujie/deploy.log 2>&1' &` 脱离会话执行。
