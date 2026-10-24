# 域名、TLS 与微信合法域名

面向本项目负责人。读完应能独立判断：域名怎么配、证书要不要自己买、微信后台填什么、出问题时先查哪里。

## 1. TLS 是什么，为什么必须要有

TLS（旧称 SSL）就是浏览器地址栏那把「小锁」。它做三件事：

1. **加密**：手机和服务器之间的内容（账号、孩子照片、题目）不会被中途读取；
2. **防篡改**：中间人改不了传输内容；
3. **证明身份**：证书由受信任机构签发，证明这个域名确实连到你部署的服务，而不是别人伪造的站。

微信小程序**强制**要求后端是 `https://`，并且域名必须在小程序后台登记。所以 TLS 不是可选项，是上线前提。

关键认知：**证书不需要花钱买，也不需要手动续期**。本项目的方案是让 [Caddy](https://caddyserver.com) 自动向 Let's Encrypt 申请免费证书（有效期 90 天），到期前自动续。你只需要保证两件事：

- 域名解析指向这台服务器；
- 服务器的 **80 端口** 对外开放（Let's Encrypt 靠它验证域名归属）。

## 2. pxcore.com.cn 的现状（实测，2026-10-24）

| 项目 | 实测结果 | 含义 |
| --- | --- | --- |
| `pxcore.com.cn` | 解析到服务器；HTTP 返回 308 跳 HTTPS | 主机上已有 Web 服务在跑 |
| `api.pxcore.com.cn` | 已有 Let's Encrypt 证书（CN 就是它本身，2026-10-11 签发，2027-01-09 到期），HTTPS 根路径返回 404 | **这个子域已被另一个小程序占用** |
| 响应头 `Server: Caddy` | 主机 80/443 由 **Caddy** 监听 | 不能再用 nginx 抢 80/443 |
| `tiyoujie.pxcore.com.cn` | 尚未解析（NXDOMAIN） | 本项目使用这个新子域，需加一条 DNS 记录 |

因此本项目的拓扑是：

```
微信小程序 / 浏览器
        │  https://tiyoujie.pxcore.com.cn   （证书由 Caddy 自动申请）
        ▼
   Caddy（主机上，占用 80/443，同时服务另一个小程序）
        │  反向代理到 127.0.0.1:18010
        ▼
   本项目容器（Django + Celery + PostgreSQL + Redis）
```

这样做的两个好处：不碰另一个小程序的站点块；应用端口只绑回环，公网无法绕过 Caddy 直连。

## 3. 配置步骤

### 3.1 加一条 DNS 记录

在腾讯云 DNSPod（或域名所在服务商）添加：

| 主机记录 | 类型 | 线路 | 记录值 | TTL |
| --- | --- | --- | --- | --- |
| `tiyoujie` | A | 默认 | 你的服务器公网 IP | 600 |

验证（本地终端）：

```bash
nslookup tiyoujie.pxcore.com.cn
# 期望看到与服务器公网 IP 一致的结果
```

> 生效通常 1–10 分钟，最长 24 小时。**DNS 没生效前不要去申请证书**，否则一定失败。

### 3.2 放行端口

腾讯云控制台 → 云服务器 → 安全组 → 入站规则，确保放行：

- `22/tcp`（你的 SSH 端口）
- `80/tcp`（Let's Encrypt 验证 + HTTP 跳转）
- `443/tcp`（正式流量）

主机内若启用了 ufw，也要放行同样端口（`infra/deploy/setup-host.sh --firewall` 会处理）。

### 3.3 让 Caddy 接管新域名

在服务器上执行（脚本会备份、校验、失败自动回滚，且只动本域名块）：

```bash
sudo ./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010 --dry-run
sudo ./infra/deploy/apply-caddy.sh --domain tiyoujie.pxcore.com.cn --upstream 18010
```

Caddy 会在收到第一个 HTTPS 请求时自动申请证书，通常 10–60 秒。验证：

```bash
curl -fsS https://tiyoujie.pxcore.com.cn/api/v1/health/live/
openssl s_client -connect tiyoujie.pxcore.com.cn:443 -servername tiyoujie.pxcore.com.cn </dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

期望：健康检查返回 `{"status":"ok",...}`；证书 `subject` 是 `tiyoujie.pxcore.com.cn`，`issuer` 是 `Let's Encrypt`，有效期约 90 天。

### 3.4 微信小程序后台

微信公众平台 → 开发 → 开发管理 → 开发设置 → 服务器域名：

- **request 合法域名**：`https://tiyoujie.pxcore.com.cn`
- 只填域名，**不带路径、不带端口、必须 https**
- 每月修改次数有限，确认后再保存
- 不要关闭「域名校验」开关

## 4. 常见问题

| 现象 | 先查什么 |
| --- | --- |
| Caddy 申请证书失败，日志出现 `challenge failed` | ① DNS 是否已指向本机（`dig +short 域名`）；② 安全组/ufw 是否放行 80；③ 是否有其它进程占用 80（`ss -lntp \| grep :80`） |
| 域名能打开但证书报错 | 站点块地址是否写成了完整域名（不能只写 `:443`）；证书文件是否被其它服务覆盖 |
| 小程序提示「不在合法域名列表」 | 后台 request 域名是否与 `VITE_API_BASE_URL` 完全一致（含子域）；是否带了端口或路径 |
| 接口 301 循环 | 反向代理没传 `X-Forwarded-Proto`，或后端没信任该头。本项目已内置 `SECURE_PROXY_SSL_HEADER`，Caddy 模板也已显式设置 |
| 80 端口被墙/被拦 | 国内主机未备案会被拦截。主域名 `pxcore.com.cn` 已备案，子域沿用同一主体一般无需单独备案；如被拦请到云厂商备案控制台确认 |

## 5. 关于「HSTS」的一句话提醒

响应头 `Strict-Transport-Security: max-age=31536000; includeSubDomains` 会让浏览器在一年内强制走 HTTPS，且**对子域同样生效**。本项目只对 `tiyoujie` 这一个站点块设置该头，不影响 `api.pxcore.com.cn` 上的另一个小程序；但如果将来要换域名或临时降级 HTTP，浏览器会在此期间拒绝访问，需要清理 HSTS 缓存。

## 6. 证书续期

Caddy 自动续期，无需 cron。确认方式是看证书到期时间是否始终保持在 60 天以上：

```bash
echo | openssl s_client -connect tiyoujie.pxcore.com.cn:443 -servername tiyoujie.pxcore.com.cn 2>/dev/null \
  | openssl x509 -noout -enddate
```

若发现到期时间不再变化，检查 Caddy 是否在运行（`systemctl status caddy`）以及 80 端口是否仍可被外网访问。
