# Phase 8 报告：真实域名接入准备与发布基线

日期：2026-10-24。范围：把项目从「本机可跑」推进到「可在现有 pxcore.com.cn 主机上一个命令发布」，并建立公开仓库与 CI 基线。

## 1. 本轮解决的真实缺陷

| 缺陷 | 影响 | 修复 |
| --- | --- | --- |
| 缺少 `SECURE_PROXY_SSL_HEADER` | 部署环境 `SECURE_SSL_REDIRECT=True`，而 TLS 由前置代理终结，Django 看到 http → 每个请求 301 到自己，**微信端会登录失败/无限跳转** | `backend/config/settings/base.py` 在 staging/prod 信任 `X-Forwarded-Proto`；新增回归测试覆盖「转发 https 返回 200 / 明文 http 仍 301」 |
| 生产覆盖层 `ports: []` 并未真正移除端口 | `ports` 是列表合并语义，dev 的 `127.0.0.1:18000:8000` 仍会残留 | 用 Compose `!override` 显式改成只绑 `127.0.0.1:${API_HOST_PORT}`；本机 `config` 实测只剩 18010 |
| 主机 80/443 已被既有 Caddy 占用 | 直接上 nginx 会抢端口，影响另一个小程序 | 新增 Caddy 覆盖层与站点块模板：仅追加本域名块，应用端口只绑回环 |
| CI 从未执行过 | 仓库无提交，流水线里的 3 处 lint 问题会直接失败 | 修复 `scripts/` 的 E731/B904/E501，并新增生产编排与 `check --deploy` 静态校验步骤 |

## 2. 新增交付物

| 文件 | 作用 |
| --- | --- |
| `infra/deploy/compose.caddy.yaml` | 主机已有 Caddy 时的覆盖层：api 绑回环、nginx 进 `standalone` profile 不启动 |
| `infra/deploy/caddy/tiyoujie.caddy.template` | 站点块：HSTS/nosniff/DENY、去 `Server` 头、9MB 请求体上限、健康检查不写日志、访问日志轮转 |
| `infra/deploy/apply-caddy.sh` | 幂等插入/替换/删除站点块，改前备份、`caddy validate`、失败自动还原 |
| `infra/deploy/setup-host.sh` | Ubuntu 24.04 初始化：Docker、日志上限、swap、时区、目录、按需 ufw |
| `infra/deploy/deploy.sh` | 构建 → 备份 → 迁移 → 起服务 → 健康检查；失败自动回滚镜像；支持 `--rollback` |
| `backend/tests/test_deploy_config.py` | 10 项部署面回归：代理头、秘密强度、https 来源、禁 dev-login、禁测试库 |
| `docs/operations/tls-and-domain.md` | TLS 科普 + pxcore.com.cn 实测现状 + DNS/证书/微信配置步骤 |
| `docs/operations/phase-8-deployment-pxcore.md` | 本主机上线手册：人工清单、发布、回滚、备份 cron、每日检查 |
| `.github/workflows/ci.yml`（补充） | 生产编排合并 + `check --deploy` 静态校验 |

## 3. 验证证据（全部本机真实执行）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量测试 | `py -3.12 scripts/project.py test` | **203 项通过**，0 失败（隔离 PostgreSQL + 真实 Redis/Worker） |
| Caddy 语法 | `caddy validate`（caddy 2.10-alpine） | PASS |
| Caddy 运行时行为 | `artifacts/phase8_caddy_rehearsal.py` | 9/9 通过：HTTPS 健康检查 200、HSTS、`Server` 头已移除、nosniff、X-Frame-Options DENY、未知路径 404、10MB 请求体被拒、无 301 循环 |
| 生产编排合并 | `docker compose config`（compose + prod + caddy） | PASS；仅发布 18010，18000 已消失；nginx 默认不启动，`--profile standalone` 时才出现 |
| 生产配置检查 | `manage.py check --deploy`（prod 设置） | `System check identified no issues (0 silenced)` |
| 代码风格 | `ruff check` / `ruff format --check` | 全通过 |
| 仓库规范 | `scripts/check_repository.py` | 231 个文件、104 处内链，0 问题 |

演练脚本只在两处偏离生产配置：监听端口改为 18443、证书改为 Caddy 内部 CA；头、请求体上限、上游参数与生产模板完全一致。

## 4. 仍然 BLOCKED 的部分

| 项 | 原因 | 解除条件 |
| --- | --- | --- |
| Let's Encrypt 真实签发 | `tiyoujie.pxcore.com.cn` 尚无 DNS 记录；主机 80 端口未验证可达 | 加 A 记录 + 安全组放行 80 |
| 真实主机发布 | 无 SSH 凭据 | 提供密码或公钥 |
| 微信登录 | 缺 AppSecret | 微信后台复制到 `.env.prod` |
| 小程序合法域名与真机 | 需在微信后台登记并上传体验版 | 域名签发后操作 |
| 备份/恢复（生产规模） | 只有本机隔离容器演练 | 上线后按手册演练一次 |

## 5. 结论

代码侧已具备发布条件：一条命令发布、失败自动回滚、证书自动签发、边缘安全头与请求体上限可验证。**但「已上线」不成立**——真实证书、真实主机、微信真机三项未执行，发布结论仍为「条件性 GO：人工闭环范围」。

下一步只需三件人工动作：加 DNS 记录、给 SSH 访问、给 AppSecret。拿到后按 [上线手册](../operations/phase-8-deployment-pxcore.md) 第 1–5 节执行即可。
