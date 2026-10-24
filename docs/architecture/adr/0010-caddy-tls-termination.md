# ADR-0010：复用主机 Caddy 做 TLS 终结，应用只绑回环

状态：已采纳（2026-10-24）。适用阶段：Phase 8 及之后。

## 背景

目标主机（腾讯云 Ubuntu 24.04，域名 `pxcore.com.cn`）实测已有一个 80/443 监听者：

- `Server: Caddy`，`Alt-Svc: h3`；
- `api.pxcore.com.cn` 已有 Let's Encrypt 证书（CN 即该子域，2026-10-11 签发，2027-01-09 到期）；
- `pxcore.com.cn` 返回 308 跳 HTTPS。

即：这台机器上已经跑着另一个小程序的站点与证书。三条约束随之出现：

1. 不能占用 80/443，否则会影响既有业务；
2. 微信小程序强制 HTTPS，证书必须真实可信；
3. 应用端口若对公网可见，`X-Forwarded-Proto` 可被伪造，进而绕过 `SECURE_SSL_REDIRECT`。

## 决策

**复用主机 Caddy 作为唯一 TLS 终结者；本项目容器只监听 `127.0.0.1:18010`；本仓库只提供站点块模板与应用侧编排，不改动其它站点。**

具体落地：

1. `infra/deploy/caddy/tiyoujie.caddy.template`：单个站点块，包含 HSTS/nosniff/DENY、移除 `Server` 头、9MB 请求体上限、健康检查不写日志、访问日志轮转、`header_up X-Forwarded-Proto https`。
2. `infra/deploy/apply-caddy.sh`：只按域名标记插入/替换/删除自己的块；改前备份、`caddy validate`、失败还原、幂等。
3. `infra/deploy/compose.caddy.yaml`：`ports: !override` 把 api 固定为 `127.0.0.1:${API_HOST_PORT}`，并把内置 nginx 放进 `standalone` profile（默认不启动）。
4. 应用侧信任代理头：`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`，仅在 staging/prod 生效。

## 放弃的方案

| 方案 | 放弃原因 |
| --- | --- |
| 主机装 nginx + certbot 抢 80/443 | 与既有 Caddy 冲突，会打断另一个小程序 |
| 用 Caddy 的 `handle` 把两个应用合到一个站点 | 需要改动别人的站点块，且共享 HSTS/CSP 影响面不可控 |
| 自签证书或走 IP + 关校验 | 微信不允许，浏览器会报警 |
| 应用直接监听 443 | 端口冲突，且把 TLS 与业务耦合，回滚粒度变差 |

## 后果

正面：

- 证书自动申请与自动续期，不需要人工买证书、不需要 cron 续期任务；
- 两个小程序互不影响：谁改自己的块，谁的配置变更；
- 应用无公网端口，代理头伪造风险消除（本机 `docker compose config` 已实测只剩回环发布）。

代价与约束：

- 依赖主机 Caddy 持续运行；Caddy 挂掉时两个站点同时不可用（属于主机级单点，已在风险清单 K15 记录）；
- 站点块的限速能力弱于 nginx 的 `limit_req`：Caddy 标准构建不带限速模块，因此限速依赖应用内 `rate_limit`（登录、导出等入口已有）；
- `includeSubDomains` 的 HSTS 只在本站点块声明，未对整域强制，避免影响 `api` 子域上的既有业务。

## 验证

- 本机用真实 Caddy 2.10 二进制 + 内部 CA 运行同一份站点块（仅改端口与证书来源）：HTTPS 健康检查 200、HSTS 生效、`Server` 头消失、未知路径 404、10MB 请求体被拒、无 301 循环。
- 生产编排合并后 `docker compose config` 只发布 18010；`manage.py check --deploy` 0 issue。
- 真实签发与真实主机执行**尚未进行**，不构成本 ADR 的验收证据。
