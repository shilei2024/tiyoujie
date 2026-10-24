# Phase 4：分析、提示与人工修订

2026-10-24。前缀 `/api/v1/`。复用 Bearer 身份、孩子范围和 20 条分页。学生只能读取获授孩子的记录；提交分析、修订和费用偏好需要监护人角色，staff 不绕过领域权限。

| 路径 | 方法 | 已实现行为 |
| --- | --- | --- |
| ai/schema/ | GET | 返回 math-analysis-v1 JSON Schema，需要登录 |
| ai/models/ | GET | 已启用、获准且支持文本/JSON/分析的模型、第三方告知、是否实测、analysis_quota_units |
| ai/preference/?family_id= | GET / POST | 仅保存本人在该家庭的 billing_mode 偏好；不保存明文密钥，不影响显式请求的模式 |
| problems/{id}/analysis-jobs/ | GET / POST | 最近 20 个分析任务；明确费用同意后创建 |
| problems/{id}/analyses/ | GET | 按时间倒序分页分析结果，附题干版本、stale、reported 和任务费用来源 |
| analyses/{id}/feedback/ | GET / POST | 修订/问题记录分页；监护人提交 `{kind: report或correction, text}`，最多 4000 字符 |
| tasks/{id}/ | GET | 沿用任务查询；新增 task_type 和 quota_units |
| tasks/{id}/cancel/ | POST | 沿用取消语义，已发送请求仍可能计费 |

分析 POST 必须含 `Idempotency-Key`（16–64 位字母数字/短横线/下划线），及 model_id、text_version_id、expected_revision、student_answer（可空，≤4000 字符）、billing_mode、notice_version、cost_confirmed=true。BYOK 另需 credential_id。题干必须是同一道题当前已人工确认的版本；不接收任意图片、Prompt、Base URL 或 task_type。模型目录、价格、预算或开关缺失时拒绝，不降级换模式。

模型仅收到已确认题干、年级、明确填写的作答和“未包含图片”的说明，不发送答案参考、孩子昵称、学校、家庭名称或内部题干 UUID。原始作答按输入快照保存；排队前编辑题干导致 Worker 拒绝发送，处理中编辑则将完成结果绑定旧版本并标 stale，不覆盖当前题干。

正式结构见 [JSON Schema](math-analysis.schema.json)。服务端另检查字符串总长度、非有限数字、HTML/脚本、明显的诊断/稳定能力标签、提示顺序等语义约束。没有作答时只能使用 unknown 根因、error_location 必须为空。关键词检查不能证明所有语义可靠，所有结果的 verification_status 强制为 unverified；当前没有确定性数学验证器。

解析版本随每次明确分析任务追加，原始 payload 不可覆盖。反馈按同一分析下的 number 递增，保留原始 AI 结果；报告问题后 reported=true，人工修订不会把结果改成“已验证”。结果、原作答和反馈随题目/孩子/账号级联删除；账本仅保留最小费用快照。

`usage/summary/` 新增 remaining_units，语义为平台体验点数。remaining_requests 为旧字段兼容别名，不能在点数系数大于 1 时解释为请求次数。OCR/分析分别由模型的 ocr_quota_units / analysis_quota_units 配置 1–20 点，任务创建时冻结；失败返还业务点数，已发生的供应商费用仍按账本处理。BYOK 不使用这些平台点数。

凭证接口的 validation_status 会随明确发起的业务请求更新：response_received、auth_failed、insufficient_balance、permission_denied、rate_limited、outcome_unknown。只更新该任务绑定的同一凭证版本，迟到响应不能为替换后的 Key 标记连接成功。response_received 只说明曾收到供应商响应，不等于答案正确或下一次可用；不额外发送收费探测。
