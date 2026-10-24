# 上线前三步人工动作手册

本文档只讲三件必须由人来完成的事：**DNS 解析、SSH 授权、小程序 AppSecret**。
其余（主机初始化、生产配置、发布、证书签发、小程序上传）由技术侧脚本完成，见
[pxcore.com.cn 上线手册](phase-8-deployment-pxcore.md)。

前置事实（2026-10-24 实测，不是推测）：

| 项 | 实测结果 | 含义 |
| --- | --- | --- |
| `pxcore.com.cn` | A 记录 → `101.43.122.182` | 主域已指向本服务器 |
| `pxcore.com.cn` NS | `seventy.dnspod.net` / `brandy.dnspod.net` | 解析由 **DNSPod** 托管 |
| 服务器 22 端口 | 可连接，认证失败 | 安全组已放行 SSH，只缺凭据 |
| 服务器 80 / 443 | Caddy 在应答 | 证书签发所需的 80 端口已通 |
| `api.pxcore.com.cn` | 已有证书（CN 即该子域），根路径 404 | **已被另一个小程序占用，不能复用** |
| `tiyoujie.pxcore.com.cn` | NXDOMAIN | 待新增，是本项目要用的域名 |
| 主域备案 | 已备案（`api` 子域已在提供 HTTPS 服务） | 子域无需重新备案 |

因此本项目固定使用 **`https://tiyoujie.pxcore.com.cn`**。

---

## 第一步：加一条 DNS A 记录

### 1.1 目标

新增 `tiyoujie.pxcore.com.cn` → `101.43.122.182` 的 A 记录。

只有域名先解析到这台服务器，Caddy 才能向 Let's Encrypt 证明"这个域名归这台机器"，
从而自动签发证书。**没有这一步，微信小程序无法调用后端**（小程序只允许 https 合法域名）。

### 1.2 操作路径（任选其一）

**路径 A：腾讯云控制台（推荐，域名在 DNSPod 且已实名）**

1. 登录 <https://console.cloud.tencent.com/>
2. 搜索并进入 **DNS 解析 DNSPod**（或"域名与网站 → DNS 解析"）
3. 在域名列表中找到 `pxcore.com.cn`，点右侧 **解析**
4. 点 **添加记录**，按下表填写
5. 点 **保存**
6. 在记录列表确认出现 `tiyoujie` 这一行，状态为"正常"

**路径 B：DNSPod 官网**

1. 登录 <https://www.dnspod.cn/>
2. **我的域名** → `pxcore.com.cn` → **记录管理**
3. **添加记录**，按下表填写 → **保存**

### 1.3 逐字段填写

| 字段 | 填什么 | 说明 |
| --- | --- | --- |
| 主机记录 | `tiyoujie` | **只填 `tiyoujie`**，不要填 `tiyoujie.pxcore.com.cn`，否则会变成 `tiyoujie.pxcore.com.cn.pxcore.com.cn` |
| 记录类型 | `A` | 不要选 CNAME / AAAA |
| 线路类型 | `默认` | |
| 记录值 | `101.43.122.182` | 服务器公网 IP，不要带端口、不要带 `http://` |
| TTL | `600` | 10 分钟。先设短一点，方便出问题时快速调整 |
| 权重 | 留空 / 默认 | 单条记录不需要 |

### 1.4 四个常见坑

1. **不要开 CDN / 云加速 / 代理**：若 DNSPod 侧开启了加速，证书签发会走 CDN 节点，
   Caddy 拿不到真实回源，签发失败。保持"仅解析"。
2. **不要加 `www`**：小程序只调用 `tiyoujie.pxcore.com.cn`，加 `www` 无用。
3. **已有泛解析 `*` 不影响**：精确记录优先级高于泛解析，可以共存。
4. **不要动 `api` 那条记录**：那是另一个小程序在用的，改了会让它挂掉。

### 1.5 如何确认生效

等 1～10 分钟后，在**你自己的电脑**上打开 PowerShell 或 CMD，执行：

```
nslookup tiyoujie.pxcore.com.cn 8.8.8.8
```

看到类似下面这两行就成功了（`Address` 后面必须是 `101.43.122.182`）：

```
Name:    tiyoujie.pxcore.com.cn
Address: 101.43.122.182
```

如果提示"Non-existent domain"，说明还没保存或还没生效，再等几分钟。
如果返回的是别的 IP，说明记录值填错了。

确认后请告诉我，我会用权威 DNS 再核验一遍，避免本地缓存造成误判。

---

## 第二步：让我能登录服务器（三选一）

服务器 IP `101.43.122.182`，SSH 端口 22 已放行。当前从我这台机器连接返回
`Permission denied (publickey,password)`，说明**服务可达、只缺凭据**。

### 方式 A（推荐）：加公钥，无需交出密码

**优点**：不用透露密码；之后发布、回滚、看日志我都能直接做；比密码更难被撞库。

**我这台机器的公钥**（可直接复制，一整行，不要换行）：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJRHAskuhPPB6BhIvkqiKdvZWpRloKp3rktvA17BRbU 879886239@qq.com
```

**操作步骤：**

1. 登录服务器。三种办法任选：
   - 腾讯云控制台 → **云服务器** → 实例列表 → 找到 `101.43.122.182` → 右侧 **登录**
     → 选 **标准登录方式（OrcaTerm 一键登录）**，输密码即可（网页终端，不需要本机装工具）
   - 或实例右侧 **更多 → 密码/密钥 → 重置密码**，重启后用 `ssh root@101.43.122.182` 登录
   - 或用你平时登录别的机器的方式
2. 登录后（root 身份）逐行粘贴执行：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJRHAskuhPPB6BhIvkqiKdvZWpRloKp3rktvA17BRbU 879886239@qq.com' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
wc -l ~/.ssh/authorized_keys
```

3. 用 `>>` 而**不要用 `>`**：服务器上很可能已有另一个小程序的部署公钥，`>` 会把它覆盖掉，
   导致那个小程序的自动部署失效。
4. 确认 `sshd` 允许公钥登录（默认允许，一般无需改）：

```bash
grep -Ei '^\s*(PubkeyAuthentication|PasswordAuthentication)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
```

若输出为空或 `PubkeyAuthentication yes`，即为正常。

5. 告诉我一声，我执行 `ssh root@101.43.122.182 hostname` 验证，
   成功会返回服务器主机名。

**验证通过后请立刻做一件事**：如果你之前把 root 密码发给了我或写在别处，改掉它——
公钥已经能登录，密码不再需要。

### 方式 B：给密码（不推荐，但可行）

- 在本对话里直接发 `root` 的密码即可（**不要发到 GitHub、不要写进任何文件**）
- 前提：服务器 `sshd` 允许密码登录。腾讯云默认镜像通常允许；若之前用密钥方式创建实例，
  可能被禁用，此时只能用方式 A。
- 我登录后第一件事是给你装好公钥，之后你可以：
  - 在腾讯云控制台 **重置实例密码**（旧密码立即失效）
  - 或在服务器上 `passwd -l root` 锁定密码登录
- 若你不希望密码留在对话记录里，选方式 A。

### 方式 C：你自己执行，我不碰服务器

我提供完整命令序列，你复制粘贴到网页终端执行；我只在公网侧做验证。
这种方式下我需要你把每条命令的输出贴回来，排查会慢一些，但完全可控。
如果需要，我可以单独生成一份"自助执行清单"。

### 顺带确认：安全组只开这三个端口

腾讯云控制台 → 云服务器 → 实例 → **安全组** → 入站规则，应满足：

| 端口 | 来源 | 用途 |
| --- | --- | --- |
| 22 | 你的常用 IP（或 0.0.0.0/0） | SSH 运维 |
| 80 | 0.0.0.0/0 | ACME 证书校验 + HTTP 跳转 |
| 443 | 0.0.0.0/0 | HTTPS |

**以下端口绝对不能对公网开放**：`18010`（应用，只绑回环）、`5432`（数据库）、
`6379`（Redis）。这三者都通过 Docker 内部网络通信，不需要任何入站规则。
如果安全组里现在有 `0.0.0.0/0` 的 5432 或 6379，请先删掉。

---

## 第三步：小程序 AppSecret

### 3.1 在哪拿

1. 用**小程序管理员**的微信扫码登录 <https://mp.weixin.qq.com/>
2. 左侧菜单 **开发** → **开发管理**（部分版本叫"开发"→"开发设置"）
3. 找到 **开发者 ID** 区块，里面有：
   - **AppID(小程序 ID)**：应为 `wx38dee0ea03214271`（与代码中 `frontend/src/manifest.json` 一致）
   - **AppSecret(小程序密钥)**：显示为 `********************************`
4. 点右侧 **重置**（首次为"生成"）
5. 按提示完成管理员扫码 + 手机短信/邮箱验证
6. 生成后**只显示一次**，立刻复制保存到本地密码管理器

### 3.2 重要风险：确认没有别人在用这个 AppSecret

**重置后旧密钥立即失效。** 如果 `wx38dee0ea03214271` 目前已经有线上后端在用它换取
openid，重置会让那个系统立刻登录失败。

上线前请确认：

- 该 AppID 是否已上线过、是否有其他后端（旧版本、第三方 CMS、外包系统）在调用？
- 若有，需要同步更新那边，或先停用那边再重置。

如果只是尚未上线的开发版，可放心重置。

### 3.3 如何交给我（两选一）

**方式一：我写进服务器（推荐，最快）**
在本对话里发给我。我会立刻用 `chmod 600` 写入服务器 `/opt/tiyoujie/.env.prod`，
并重启 API 使配置生效；随后你可以随时在微信后台再重置一次密钥，只更新服务器上的值。

**方式二：你自己填（不经过我）**
在服务器上执行下面这段，密钥通过交互式输入，**不会留在 shell 历史里**：

```bash
cd /opt/tiyoujie
read -rsp 'AppSecret: ' S && echo && python3 - "$S" <<'PY'
import sys, pathlib
secret = sys.argv[1]
path = pathlib.Path('.env.prod')
lines = path.read_text(encoding='utf-8').splitlines()
out, done = [], False
for line in lines:
    if line.startswith('WECHAT_APP_SECRET='):
        out.append('WECHAT_APP_SECRET=' + secret)
        done = True
    else:
        out.append(line)
if not done:
    out.append('WECHAT_APP_SECRET=' + secret)
path.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('written')
PY
unset S && chmod 600 .env.prod && cd /opt/tiyoujie && docker compose -p tiyoujie --env-file .env.prod -f compose.yaml -f infra/deploy/compose.prod.yaml -f infra/deploy/compose.caddy.yaml up -d --wait api worker beat
```

### 3.4 为什么这一步不能省

生产环境关闭了开发登录（`DEV_LOGIN_ENABLED=0`），微信登录是**唯一**的登录入口。
`WECHAT_APP_ID` 或 `WECHAT_APP_SECRET` 任一为空，登录接口直接返回
`503 WECHAT_NOT_CONFIGURED`，用户进不了应用。

### 3.5 验证方式

配置完成后，以下接口无需登录即可访问：

```bash
curl -s https://tiyoujie.pxcore.com.cn/api/v1/auth/capabilities/
```

正确结果应包含：

```json
{"dev_login_available": false, "wechat_configured": true, "guardian_notice_version": "2026-10-v1"}
```

- `wechat_configured: true` → 密钥已生效
- `dev_login_available: false` → 证明生产环境没有开测试登录（这是好事）

真正的端到端验证要等小程序真机登录，我会上传体验版后请你用手机测。

---

## 三件事完成后，我这边会做什么

按顺序执行，每步都有验证，任一步失败立即停止并回滚：

| 步骤 | 动作 | 验证 |
| --- | --- | --- |
| 1 | 权威 DNS 查询确认 `tiyoujie` 指向正确 IP | `nslookup @8.8.8.8` + DNSPod 权威 DNS |
| 2 | SSH 登录，确认 Ubuntu 版本、磁盘、内存、已有 Caddy 版本与站点块 | 输出 `ls /etc/caddy/conf.d/`，确认不动 `api` 站点块 |
| 3 | `setup-host.sh`：装 Docker（若无）、限制日志大小、开 swap、设时区 | `docker version`、`docker info` 日志驱动 |
| 4 | `git clone` 仓库到 `/opt/tiyoujie`，写 `.env.prod`（随机口令、`chmod 600`） | 文件权限、必需变量齐全 |
| 5 | `docker compose build` 构建镜像并打 digest | 记录 `sha256:` 供回滚 |
| 6 | 启动 API/Worker/Beat，跑迁移 | `health/ready/` 返回 200 |
| 7 | `apply-caddy.sh` 追加 `tiyoujie` 站点块，`caddy reload` | 只新增块，`api` 站点块字节不变 |
| 8 | 等待 Let's Encrypt 签发 | `openssl s_client` 看签发者、有效期 |
| 9 | 全链路验证 | capabilities、上传图片、登录态、跨域、限速、HSTS |
| 10 | 构建小程序，上传体验版 | 你手机扫码实测 |

回滚：任一步失败执行 `infra/deploy/deploy.sh --rollback`，镜像与站点块都会退回上一版。

---

## 需要你提供的清单（勾掉即完成）

- [ ] DNS：`tiyoujie` A 记录 → `101.43.122.182`
- [ ] SSH：公钥已加入 `authorized_keys`（或提供密码）
- [ ] AppSecret：已确认无其他系统在用，并已提供
- [ ] 确认安全组未对公网开放 5432 / 6379 / 18010
- [ ] 确认隐私政策与监护人告知版本（`2026-10-v1`）可用，或告知需调整

以上任一项缺失，公开发布保持 **NO GO**；人工范围（错题、题单、复习、导出）在
AppSecret 到位后即可对真实用户开放。
