# API 初稿

日期：2026-10-22。health 与 Phase 2 身份/家庭/凭证/权益已实现，准确路径见 [Phase 2 API](phase-2-api.md)。本文其余部分为后续设计草案，不能以草案替代实际接口。尚未生成可发布的 OpenAPI。

## Phase 1 已实现接口

基础设施路由为 GET `/api/v1/health/live/` 与 GET `/api/v1/health/ready/`，均可匿名访问且禁止缓存，响应头有服务端生成的 X-Request-ID。业务接口另见 Phase 2 实际文档。

live 返回 200：`{"status":"ok","service":"tiyoujie","ai":"disabled"}`。ready 检查 PG 必要迁移和 Redis PING；正常 200，否则 503。不返回连接参数或原始异常，health 变更方法返回 405。后台入口现为 `/admin/`。

API 位于本地 127.0.0.1:18000，尚非正式 HTTPS 服务。DRF 默认要求 Bearer 认证，只对显式公开视图例外。

## 共同约定

- 版本前缀 `/api/v1/`；UUID；UTC ISO 8601 时间，显示时按用户时区转换。
- 客户端用短期不透明 access token、轮换 refresh token；后端只存 token 哈希和撤销状态。管理后台使用安全 session cookie、CSRF 和单独角色授权。令牌不放 URL，不记录头。
- family_id/child_id 是选择范围，不是授权证明；创建、列表、详情、修改、下载、导出、子资源关联均验证实际成员与孩子访问范围。跨作用域对象统一 404，避免泄漏存在性。
- 分页 `page/page_size`，page_size 上限服务端配置；错题排序 `-created_at,-id`，过滤年级/学期/章节/知识点/错误类型/日期/q。
- 异步创建 `202` 返回 task_id/status/status_url；轮询带退避。任务状态在数据库，不靠客户端开页保活。
- 付费任务、领取权益、导出/删除请求必须 Idempotency-Key；作用域 family/actor/operation/key，保存请求摘要和结果。同键同内容重放返回同结果，同键不同内容 409。题目文本 PATCH 带 If-Match/version 防并发覆盖。
- 统一失败为 `error.code/message/request_id/details`，不透传供应商正文、SQL 或 traceback。429 返回可重试时刻；敏感配置、任务和内容响应禁止公共缓存。

## 身份、授权、凭证与权益（Phase 2）

| 方法 / 路径 | 行为与权限 |
| --- | --- |
| POST `/auth/wechat-login` | code 服务端换取身份；限定 AppID；前端不得自报 openid；返回平台令牌 |
| POST `/auth/refresh`；POST `/auth/logout` | refresh 单次轮换，重用检测撤销令牌族 |
| GET/POST `/families`；GET/PATCH `/families/{id}` | 仅已授权家庭；修改要求管理权限 |
| POST `/families/{id}/invitations` | 限时单次邀请；学生关联孩子，家庭角色不能任意提升 |
| GET/POST `/children`；GET/PATCH/DELETE `/children/{id}` | 昵称/可选年级等最少数据；DELETE 创建清理任务 |
| POST/DELETE `/children/{id}/guardian-consents/{scope}` | 记录版本/用途/Provider；撤回后拒绝未发送外部任务 |
| GET/PATCH `/ai-preferences` | 首选模式/provider/model；不改变既有任务、不自动触发调用 |
| GET `/providers` | 返回审核能力目录与核对状态；不返回秘密 |
| GET/POST `/provider-credentials` | POST 接收 Provider ID 和一次性 key；GET 只返回本人凭证掩码、版本、启停和验证状态 |
| POST `/provider-credentials/{id}/validate` | 仅凭证拥有者；有费用则明确说明并限制；异步验证任务 |
| POST `/provider-credentials/{id}/replace` | 仅拥有者；credential_version 原子递增；不回读旧值 |
| PATCH/DELETE `/provider-credentials/{id}` | 停用/删除；旧版本未发送任务失效；可授权管理员仅撤销 |
| GET `/entitlements/me` | 功能清单、starts_at/expires_at、有效/到期、基础访问权；不等价 AI 余额 |
| GET `/promotion-campaigns/eligible` | 服务端资格和可见权益；不发放 |
| POST `/promotion-campaigns/{id}/claim` | 事务防重复/名额；不接受客户端到期时间 |

## 错题与 OCR（Phase 3）

| 方法 / 路径 | 行为与权限 |
| --- | --- |
| GET/POST `/problems`；GET/PATCH/DELETE `/problems/{id}` | 输入孩子范围、来源、分类；只列当前可访问内容；删除异步清理 |
| POST `/problems/{id}/assets` | multipart 单文件，多图重复上传；字节/像素/真实格式校验，返回私有 asset_id，不返回本地路径 |
| POST `/assets/{id}/transforms` | 裁剪/旋转区域经服务端验证，创建新资产版本；支持分题引用 |
| POST `/assets/{id}/download-tickets` | 鉴权后短时访问；开发本地用受控流，生产默认同源鉴权网关；原生 S3 URL 须说明 TTL 内撤销限制 |
| POST `/problems/{id}/ocr-jobs` | 明确 billing_mode、provider/model、credential_id（仅 BYOK）、input_version、告知记录；后台预留 |
| GET `/tasks/{id}`；POST `/tasks/{id}/cancel` | 当前授权范围；返回状态、稳定错误码和费用占用状态，不返回秘密 |
| GET `/problems/{id}/text-versions` | 原始 OCR 与修订分别展示，权限与错题一致 |
| PATCH `/problems/{id}/text` | If-Match 校验后创建新版本并确认，不修改 OCR 原文 |

自动校对不作为定稿。低置信度/符号不确定进入 needs_review；没有 Provider 时可人工录入，但不得展示伪造的识别成功。

## 分析、题库与复习（Phase 4–6）

| 方法 / 路径 | 行为与权限 |
| --- | --- |
| POST `/problems/{id}/analysis-jobs` | 只接受已确认版本；绑定模式、能力/价格/模板版本；不得未经请求自动 OCR 后连调 |
| GET `/usage/summary` | 同范围的平台额度/平台成本与 BYOK 参考用量分栏；unknown 不记零 |
| GET `/problems/{id}/similar-questions` | 仅合法审核题库或当前家庭自有题；返回来源/权利/答案状态/匹配理由 |
| POST `/problems/{id}/generation-jobs` | 数量/难度/意图有上限；输出保持 AI 待核验 |
| GET/POST `/practice-sets`；GET `/practice-sets/{id}` | 校验孩子及每个固定题目版本来源权限 |
| POST `/attempts`；GET `/review-tasks` | 绑定明确题目版本；可选耗时/自评；不信任客户端传入掌握度 |
| POST `/review-tasks/{id}/reschedule` | 配置允许范围内调整并审计，不跳过所有权 |
| GET `/reports/overview` | 样本量、窗口和算法版本；不足样本明确说明 |
| POST `/data-export-jobs` | 历史数据基础导出在会员到期后仍可用；下载同样受权限与删除状态控制 |
| POST `/account-deletion-jobs` | 有效身份与明确删除范围确认；冻结新任务、清理进度、最少审计 |

## 管理 API / 后台

Phase 2 起 Django Admin 提供最小活动配置及有原因的权益调整；后续管理题库审核、JSON 导入预览/确认、知识点、能力/价格/预算、任务重试与分账指标。高风险修改要求专用角色、理由、版本与审计。管理 API 若后续新增，使用 `/api/v1/admin/`，不能由普通 is_staff 直接获得全域数据读权限。

## 项目错误码

AUTH_REQUIRED、CONSENT_REQUIRED、NOT_FOUND、VERSION_CONFLICT、IDEMPOTENCY_CONFLICT、UPLOAD_INVALID、UPLOAD_TOO_LARGE、QUOTA_EXHAUSTED、PLATFORM_DISABLED、BUDGET_EXHAUSTED、BUDGET_RECONCILIATION_REQUIRED、CREDENTIAL_REVOKED、PROVIDER_AUTH_INVALID、PROVIDER_PERMISSION_DENIED、PROVIDER_BALANCE_INSUFFICIENT、PROVIDER_QUOTA_EXHAUSTED、PROVIDER_ACCOUNT_UNAVAILABLE、PROVIDER_RATE_LIMITED、MODEL_CAPABILITY_MISMATCH、PROVIDER_TIMEOUT、AI_OUTPUT_INVALID、ENTITLEMENT_REQUIRED、CAMPAIGN_INELIGIBLE、TASK_CANCEL_PENDING。

基础设施故障与余额不足分开；平台预算故障返回服务不可用，不引导用户重复提交付费请求。详情只包含可安全展示的操作建议。
