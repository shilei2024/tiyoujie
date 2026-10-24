# Phase 2 本地运维

日期：2026-10-22。以下仅为当前本地实现，生产部署/完整恢复仍未验收。

## 初始化与后台

先按 [本地手册](../development/local-development.md) 安装、构建、迁移，再显式配置基础限额。未配置时家庭创建与档案额度查询返回 SITE_NOT_CONFIGURED，不悄悄启用活动。`configure_limits` 参数有范围验证且记录原因。

管理员通过终端交互创建，密码不要放命令参数或日志：

```powershell
docker compose -p tiyoujie-local run --rm --no-deps api python manage.py createsuperuser
```

打开本地 `/admin/`，需独立后台登录和 CSRF。Admin 静态资源在镜像构建时收集，不使用真实运行时秘密。超级管理员可授权运营人员活动/限额/权益的必要 model 权限；不要把超级管理员权限发给测试身份。普通运营人员不能管理账号状态；账号停用由超级管理员填写原因，撤销会话。

活动默认 draft；运营填写窗口、时区、期限（默认 6 月）、功能、档案限额、容量、是否允许已有用户、互斥组与提醒天数，再显式 active。本地没有生效活动种子；没有创建默认 Admin 密码。所有配置/调整操作必须填写原因，不要在原因填秘密或孩子身份资料。

权益 Admin 只可调整到期时间/撤销时间，功能快照只读；补发使用命令，并检查操作员 active/staff 与 add_entitlementgrant 权限：

```powershell
docker compose -p tiyoujie-local run --rm --no-deps api python manage.py grant_entitlement --actor-id 运营账号数字ID --family 家庭UUID --campaign 活动UUID --reason "Support request"
```

补发仍遵守窗口/资格/容量/重复规则，不绕过暂停。命令参数均为对象 ID 与原因，不传凭证。命令未在真实运营账号上执行，服务层有权限与审计测试。

## 凭证主密钥

显式为本机增加随机 32 字节主密钥：

```powershell
py -3.12 scripts/bootstrap.py --with-credential-key
```

只有密钥配置两项都不存在才生成，已有秘密不覆盖。忽略的 .env 中保存 CREDENTIAL_KEYS_JSON（版本名到 base64 32 字节值的 JSON）与 CREDENTIAL_ACTIVE_KEY_VERSION。真实部署应通过受控秘密注入和 ACL 管理，不能复制本地 .env 或把值填入 .env.example、命令行、工单、截图和仓库。

密文使用 AES-256-GCM，主密钥不派生自 Django SECRET_KEY。用户密钥只能 HTTPS 提交，API 仅回掩码，后台不注册凭证表。本地 HTTP 验收只能查元数据；测试 secure=True 不是 TLS 实测，不能关闭服务器检查来方便演示。

轮换流程：

1. 暂停凭证写入和相关任务；备份数据库，把旧主密钥单独受控备份，不与密文一同分发。
2. 通过秘密管理渠道生成新 32 字节值，把新旧版本同时注入 keyring；active 设为新版本，重建本项目 API/Worker/Beat 配置。全过程不回显秘密。
3. 运行 `rotate_credential_key --to-version v2`，参数只有版本名。命令事务内重新加密全部未删除凭证（包括停用项），失败回滚，记录主密钥版本审计，不改变用户凭证版本。
4. 在受控维护环境检查剩余旧 key_version 数量为 0，再恢复写入。保留旧版本直到旧备份过期并完成独立恢复验证；不要立即删除唯一可解密备份的密钥。

轮换算法已用生成测试密钥验证，新旧真实部署密钥轮换未演练。密文/nonce/认证附加数据损坏会拒绝解密，不调用其他账户或平台凭证回退。

## 删除与任务恢复

孩子删除先标记不可访问并撤回授权，后台清理档案与关联记录；账号注销先撤销全部业务会话。自己拥有家庭仍有其他活跃成员时拒绝注销，避免直接影响其他人。家庭中的外来成员注销只删除其成员关系/自有凭证，不删除其他 owner 的家庭。

API 提交后发布任务，Beat 每分钟扫描 queued 记录，处理发布失败和 Worker 崩溃；重复执行不会重复清理。查询凭据放 X-Deletion-Receipt，仅保存哈希。数据库任务回执和最小审计不随账号清除；未来需在正式隐私/保留策略中确定其留存周期。

本轮真实 Worker 已清理专用验收孩子/账号，未删除其他用户资料。恢复备份时必须重放已完成删除清单，避免恢复已删资料；完整 DB/私图/tombstone 恢复工具与演练属于 Phase 7，当前没有恢复通过结论。

## 定时任务

仅运行一个 Beat，保持 API、Worker、Beat 镜像一致。到期权限由服务端查询即时判定，不靠 Beat。提醒只发站内通知，配置节点的 24 小时窗口内重试且不重复；没有微信/SMS/邮件发送或支付动作。普通 up 关闭本机测试登录，down 保留所有数据卷。
