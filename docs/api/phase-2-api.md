# Phase 2 实际 API

日期：2026-10-22。路由依据 backend/config/urls.py；前缀 `/api/v1/`，所有路径带结尾 `/`。未来偏好、供应商验证、OCR、AI 等草案尚未实现。

## 协议和权限

JSON 请求，未知字段/类型错误 400。失败体 `error.code/message/request_id`，不透传 SQL、供应商正文或堆栈。响应 no-store 并带 X-Request-ID。除明确公开的接口外要求 `Authorization: Bearer <access_token>`；令牌不放 URL。

access 15 分钟，refresh 会话 14 天；数据库只存哈希，refresh 单次轮换，重用撤销整个会话。前端只在内存保留会话。公开登录和敏感操作 Redis 原子限流，每类每分钟默认 20 次；超限 429，限流器故障 503。

家庭 owner 由服务端确定。owner 可见家庭全部孩子，其他监护人/学生仅可见明确授予的孩子；学生只读。跨范围通常 404，范围内缺角色 403。staff/superuser 在业务 API 没有跨家庭特权。后台独立 session/CSRF，仅配置管理权限。

家庭/孩子列表分页为 count/page/next/results，每页 20，`?page=1`；next 为下一页数字或 null。范围参数 family_id 是选择条件而非授权证明。

## 身份

| 方法 / 路径 | 输入与结果 |
| --- | --- |
| GET `auth/capabilities/` | 公开；测试登录可用标志、微信配置状态、当前告知版本 |
| POST `auth/dev-login/` | 公开入口默认 404，显式 dev 开关后接受 identity（3–32 位 ASCII 字母数字/下划线/短横线），返回标记测试身份的令牌 |
| POST `auth/wechat-login/` | 公开；仅 code，服务端固定 HTTPS 微信接口校验；拒绝客户端 openid。缺配置 503，不回传 openid/session_key |
| POST `auth/refresh/` | 公开；refresh_token，返回新令牌对 |
| POST `auth/logout/` | 撤销当前会话，204 |
| GET `auth/me/` | 当前用户 ID 与 is_test_login，无微信身份秘密 |

微信兑换不允许重定向，限制超时和响应大小；只有单元模拟证明，没有真实微信验收结论。

## 家庭、孩子、授权和删除

| 方法 / 路径 | 行为 |
| --- | --- |
| GET / POST `families/` | 列出已加入家庭；创建传 name，服务端限额检查。列表含 id/name/owner_id/role/created_at |
| GET / PATCH `families/{id}/` | 读取成员家庭；修改 name 仅 owner |
| GET / POST `children/` | 列表传 family_id；创建仅 owner，输入 family_id/nickname/guardian_confirmed=true/当前 notice_version；可选 grade(1–12/null)、semester、textbook |
| GET / PATCH `children/{id}/` | 读取/更新可见孩子；更新要求监护人和有效 profile 授权，不能改变 family_id |
| POST `children/{id}/update/` | 与 PATCH 共用验证、锁和权限；页面统一使用此路径兼容微信 |
| DELETE `children/{id}/` | 监护人 confirm=true，202，立即隐藏并由后台清理 |
| GET / POST `children/{id}/consents/` | 监护人；POST scope=profile/deepseek/kimi 和当前 notice_version。同用途新授权撤销旧授权，DB 限制只保留一个有效版本 |
| DELETE `children/{id}/consents/{consent_id}/` | 撤回授权，204；profile 撤回后停止编辑，保留读取和申请删除 |
| POST `families/{id}/invitations/` | owner；role=guardian/student、同家庭 child_ids（1–20），返回一次显示的 invitation_token 和 expires_at；24 小时单次有效 |
| POST `invitations/accept/` | 当前用户传 invitation_token，事务消费；过期或重复拒绝 |
| GET `families/{id}/members/` | owner；活跃成员 ID/user_id/role |
| DELETE `family-members/{id}/` | owner 移除其他成员，同时撤销孩子范围和其全部业务会话；不能移除 owner |
| POST `account-deletion-jobs/` | confirm=true；自己拥有家庭仍有其他成员时 409。受理后立即停用账号/会话，后台清理自有家庭和账号 |
| GET `deletion-requests/{id}/` | 公开入口但要求 X-Deletion-Receipt，错误或缺失 404，只返回 task_id/status/completed_at |

删除回执为 task_id/status/deletion_receipt，receipt 只显示一次，DB 只存哈希。任务按数据库状态幂等，发布失败由 Beat 扫描恢复。API 暂无通用 Idempotency-Key 重放；重复 DELETE 可返回 404，不能把当前删除任务规则用于未来付费任务。审计保留最小操作 ID/原因，不保留孩子资料或秘密原值。

## 服务凭证

仅活跃家庭监护人管理自己创建的凭证，学生 403、其他拥有者/家庭 404。创建与替换原值同时要求 HTTPS；不信任客户端转发头。没有明文查询/解密接口，也没有后台凭证表。

| 方法 / 路径 | 行为 |
| --- | --- |
| GET / POST `provider-credentials/` | GET 传 family_id；POST family_id/provider(deepseek/kimi)/key，一次性接收原值 |
| GET / PATCH / DELETE `provider-credentials/{id}/` | 读取元数据；PATCH 仅 enabled；DELETE 清除密文/nonce/尾号并停用 |
| POST `provider-credentials/{id}/state/` | 与 PATCH 相同，页面使用 POST 兼容小程序 |
| POST `provider-credentials/{id}/replace/` | 一次性 key，递增 credential_version |

返回字段仅 id/family_id/provider/masked_key（末四位）/enabled/credential_version/validation_status/updated_at。validation_status=not_verified，不能当作连接成功。启停/替换/删除使旧版本任务不可使用；服务层还检查当前用户、启用状态和精确版本，尚无 AI 外发任务。

AES-256-GCM 使用随机 nonce，认证附加数据绑定凭证 ID/家庭/供应商/版本；主密钥与 Django SECRET_KEY 独立，缺失或格式错误时拒绝存储，主密钥版本不返回 API。

## 权益与通知

| 方法 / 路径 | 行为 |
| --- | --- |
| GET `entitlements/me/?family_id=...` | 当前家庭；grants、档案限额、ai_mode=disabled、automatic_billing=false |
| GET `promotion-campaigns/eligible/?family_id=...` | owner；服务端资格/容量查询 |
| POST `promotion-campaigns/{id}/claim/` | owner；仅 family_id；事务发放，同家庭同活动重复返回原记录，不延长 |
| GET `notifications/?family_id=...` | owner；最近 50 条站内提醒 |

活动默认草稿，期限默认 6 自然月（可设 1–24），检查窗口、新旧用户规则、互斥组、历史领取与容量。月底裁剪至目标月末，歧义时刻拒绝发放。家庭/活动行锁和 DB 唯一约束防重复和容量竞争；权益快照不随活动编辑改变，暂停活动不撤销已发权益。

授权实时检查到期，无需等待任务。提醒节点显式配置，在节点 24 小时窗口内事务幂等重试，停机超过窗口不补发堆积通知。到期只记事件、不扣费、不删数据。当前仅扩展档案额度有对应功能实现，其他报告/导出仍未开发。

方法兼容依据：[uni-app request 官方文档](https://uniapp.dcloud.net.cn/api/request/request.html)。没有通过强制类型断言向微信发送 PATCH。
