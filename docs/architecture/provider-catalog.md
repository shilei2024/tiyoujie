# Provider 能力核查记录

核查日期：2026-10-22，Asia/Shanghai。**以下为官方文档核查，不是账号可用性、真实推理或数学/OCR 准确率实测。所有 Provider 的 integration_verified 均为 false，平台调用默认关闭。**

## 预置端点与模型候选

| Provider / 模型 | 官方端点 | 官方文档所示能力 | 项目状态 |
| --- | --- | --- | --- |
| DeepSeek `deepseek-flash` | `https://api.deepseek.com`，OpenAI 格式 | 图像+文本、JSON output | 文字/视觉候选；待真实账号与 Schema 验证 |
| DeepSeek `deepseek-v4-pro` | 同上 | 文本与 JSON；当前价格页明确不支持 vision | 不得用于图片任务 |
| Kimi `kimi-k3` | 中国站 `https://api.moonshot.cn/v1` | 原生视觉；可按模型参数调用 | 视觉候选，未测 OCR 和成本 |
| Kimi `kimi-k2.6` | 同上 | 文本/视觉、多模态能力 | 备用候选，任务调用前仍需精确能力记录 |

DeepSeek 官方视觉页当前推荐 deepseek-flash；旧 flash/vision-exp 别名对应模型已退役，不作为新项目硬编码 ID。Kimi 官方模型列表列 kimi-k2.5、moonshot-v1 等旧系列已下线，不沿用旧教程。中国站/国际站 Key 与账单不混用；MVP 默认中国站预置端点，不启用任意 Base URL。

“JSON output / JSON Mode”不等于供应商严格保证本项目 JSON Schema；必须由后端独立校验字段、类型、长度、数学格式及不确定性。文档没有足够证据的 capability 标记 unknown，所需能力 unknown 也应拒绝该任务。

## 能力目录必须保存

Provider、精确 Model ID、协议、输入/输出模态、supports_vision、json_mode、strict_schema（独立字段）、上下文/输出/图片限制、价格版本引用、官方来源、checked_at、启停、文档与真实验证分别记录。模型是配置而非业务代码常量；停用后阻止新任务，旧记录保留原版本。

图片尽量以有界 base64 的必要区域发出，避免给供应商可长期访问的私图 URL，也不使用服务商 Files 持久上传作为默认。若后续启用供应商文件接口，需要单独记录留存、删除和生命周期策略。

## 错误归一化

| 供应商结果 | 项目错误与动作 |
| --- | --- |
| DeepSeek 401；Kimi 401 | PROVIDER_AUTH_INVALID；提示更换/核对 Key，停止重试 |
| DeepSeek 402；Kimi 429 的 exceeded_current_quota_error | 按受控错误字段区分余额不足、额度不足或账号停用；不能只按 HTTP 状态推断或自动重试 |
| Kimi 403 permission_denied_error | PROVIDER_PERMISSION_DENIED；提示账号/API/IP 授权问题，不当成余额不足 |
| 400 / 422 参数或输入不兼容 | PROVIDER_INPUT_INVALID / MODEL_CAPABILITY_MISMATCH；修正输入，不重复收费试探 |
| 429 且确认为速率/并发限制 | PROVIDER_RATE_LIMITED；尊重 Retry-After（如有），只有费用状态明确且重新预留才重试；额度不足不进入退避重试 |
| 5xx / 连接中断 / 超时 | PROVIDER_UNAVAILABLE / PROVIDER_TIMEOUT；区分未发送与可能已收费，不自动释放未知费用 |
| 拒答 / 内容过滤 | PROVIDER_REFUSED；明确失败原因，不伪装成成功分析 |
| JSON 无效或 Schema 不通过 | AI_OUTPUT_INVALID；结果不入正式解析；上游已收费仍记账 |

供应商错误正文只经受控分类，不原样回传或记录。Kimi 限速涉及并发、RPM/TPM/TPD，具体账号等级限制未获取；DeepSeek 也需按供应商实际约束节流，不能把文档上限当作本账号可用额。

## 价格与验证

官方定价包含按 token 的输入/输出/缓存等维度，DeepSeek 还区分时段。本文不将价格数值作为生效配置。管理员需将有效币种、单价、单位、计费项和上界公式保存到不可变 PriceVersion；未知价格或计费能力阻断平台请求。BYOK 估算与平台成本分开，供应商账单为最终参考。

每个 Provider 的真实验收需要：有效测试凭证、所属站点核对、元数据/低成本连接检查、短文本 JSON、经授权脱敏单图、图片能力错误、余额/鉴权/限速/超时处理、用量与价格版本、轮换删除及日志扫描。失败注入可在单元测试中使用 fake，但必须明确真实供应商路径未覆盖。

## 官方一手来源

- [DeepSeek 模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[视觉输入](https://api-docs.deepseek.com/guides/vision/)、[错误码](https://api-docs.deepseek.com/quick_start/error_codes/)。
- [Kimi 快速开始与端点](https://platform.kimi.com/docs/get-api-key)、[模型列表及退役记录](https://platform.kimi.com/docs/models)、[视觉能力](https://platform.kimi.com/docs/guide/use-kimi-vision-model)、[JSON Mode](https://platform.kimi.com/docs/guide/use-json-mode-feature-of-kimi-api)。
- [Kimi 错误码](https://platform.kimi.com/docs/api/errors)、[限速](https://platform.kimi.com/docs/pricing/limits)、[计费单位](https://platform.kimi.com/docs/pricing/chat)。

需要编码时重新核对上述内容，尤其模型退役、参数、价格和数据留存政策。本轮未核实完整供应商留存/训练条款，不能向用户承诺第三方不留存或不训练；该告知缺项阻止公开服务外发。
