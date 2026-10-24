# Phase 4：分析路由、运营预警与版本

2026-10-24。承接 [Phase 3 存储与费用运维](phase-3-operations.md)，不启用外发、不新增真实模型/价格/预算种子，不改变平台与 BYOK 的费用主体。

## 运行边界

分析外发由 AI_ANALYSIS_ENABLED 单独控制，OCR 仍使用 OCR_OUTBOUND_ENABLED；平台模式还需 PLATFORM_AI_ENABLED、BudgetPolicy 和 Worker 凭证。所有开关默认关闭，现有 dev/test Worker 网络仍为 internal。真实外发前须完成合法配置、隐私条款、样本和费用上界审核；本轮无真实服务商调用。

ModelRouter 按明确选择的 provider/model/task_type 检查能力，不自动找其他模型或换费用模式。OCRModel 表沿用历史名称，分析模型需同时具备 supports_text、supports_json、analysis_enabled、runtime_approved 和有效第三方告知；不要求文本分析模型支持图片。价格上界必须覆盖完整转录/分析提示和最大输入/输出，不能把合成测试价格用于生产。

任务沿用 OCRJob/Outbox/UsageLedger 表和已有 Worker 领取逻辑，新增 task_type=analysis。相同策略行锁与四类金额窗口、三类业务额度保证 OCR 和分析共享硬预算。OCR 和分析的体验点系数分别配置在模型上，默认 1，范围 1–20，创建任务时冻结。BYOK 不扣平台点数或金额预算，仍受公平使用上限约束。

新增 AnalysisInput、Analysis、AnalysisFeedback、ServicePreference。输入摘要绑定题干版本、作答和年级；供应商请求不包含内部 UUID。原始分析和人工修订为追加历史，数据库触发器阻止修改内容、换题和切换任务种类。修订只是人工记录，不能自动升级为数学已核验。

## 预警与对账

BudgetPolicy.alert_at_percent 配置 1–100% 的预警阈值，默认 80%。按“已结算 + 预占”的保守金额判断，每个预算窗口只写一条 platform_budget_warning；不是供应商最终账单阈值。未知费用记录 platform_cost_unknown 并熔断，超出审核上界继续记录 platform_bound_exceeded。所有记录仅含预算/任务标识、时间和受控原因，不含题干、作答、密钥或供应商原文。

管理员需具有 accounts.view_auditevent 权限，在 Admin 的审计记录中只读取 platform_ 开头的运营事件；不提供编辑、删除或用户业务记录入口。通知范围为后台持久记录，没有未经授权发邮件、短信或外部消息。日窗口预警随新窗口重新计数，累计窗口保留一次预警。硬上限与熔断独立于预警，不能用预警替代限额。

未决费用按既有 reconcile_ocr 命令核实，即使任务类型是 analysis 也使用同一账本和命令；没有静默重发。对账后恢复仍需显式审计操作，管理表单锁策略行后再校验。BYOK 连接状态只随明确业务请求更新，Key 替换/启停重置状态，迟到响应不能污染新版本。

## 升级与验证

本轮新增 OCR 两个、ai_tutor 两个和 metering 一个迁移，共 5 项；累计 34 项。readiness 要求三个 app 的最新必要迁移。升级前按实际目标环境备份 DB、私图和独立主密钥，不通过删卷/反向删表回退；有新增分析资料时，回退前必须处理排队任务和未决费用，审查格式兼容性。完整独立恢复演练仍待 Phase 7。

`project.py test` 在隔离 PG/Redis/私图卷运行测试，随后跑真实 nonce、OCR 禁止外发、分析禁止外发三类 Worker 探针。最后两类必须 sent_at=NULL、4 个预算/3 个点数窗口预占归零，并清理自身合成资料。它们不是供应商识别/解析质量验证。

真实数学解析质量、真实双模式费用、微信联网及真机交互待合法配置后补验收。Schema/关键词规则只是一层限制，无法保证推理或语义完全正确，所有分析/答案候选始终待核验。确定性验证器在 Phase 5 实现，不提前宣称“已验证”。
