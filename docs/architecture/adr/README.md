# 架构决策索引

日期见各记录。Accepted for design 只表示当前设计基线，未声称代码或运行验收已完成；历史结论保留，最新实际结果见 Phase 3 报告。

| ADR | 主题 | 状态 |
| --- | --- | --- |
| [0001](0001-scope-and-conflicts.md) | 阶段范围、冲突和推进边界 | 设计基线；PRD 真实原型仍待验证 |
| [0002](0002-stack-and-versions.md) | 技术路线、版本与兼容性 | 候选版本；Phase 1 锁定及实测 |
| [0003](0003-ai-credentials-and-budgets.md) | 混合 AI、密钥、事务预算、重试 | Accepted for design |
| [0004](0004-promotion-entitlements.md) | 自然月权益、资格和到期 | Accepted for design |
| [0005](0005-phase1-toolchain.md) | Phase 1 实际工具链、隔离与安全阻断 | 功能验证完成；安全门禁失败 |
| [0006](0006-phase2-local-continuation.md) | 用户继续指令和 Phase 2 本地边界 | 已实施；外部验收及依赖门禁保留 |
| [0007](0007-phase3-private-ocr.md) | 私图、文本历史与首个 OCR 费用入口 | 本地实现已验收；真实 OCR 与公开发布阻断 |
| [0008](0008-phase4-wechat-analysis.md) | 微信开发与分析任务、版本、费用保护 | 已实施；真实外部能力与界面交互待验收 |
| [0009](0009-phase6-review-and-export.md) | 复习调度、题单快照与渲染时导出 | 已实施；真实样本与 PDF 能力待评估 |
| [0010](0010-caddy-tls-termination.md) | 复用主机 Caddy 做 TLS 终结，应用只绑回环 | 已实施；真实签发与主机执行待完成 |
