# 题有解

每道错题，都有下一步。

面向家长与学生的数学错题管理与智能复习系统，目标为微信小程序、Web 管理后台和可部署到自有服务器的独立后端。

## 当前交付

2026-10-24：已推进至 Phase 8。Phase 5 交付题库导入、权利审核、数学核验、检索与变式草稿；Phase 6 交付题单、作答、间隔复习、趋势与渲染时导出；Phase 7 交付备份/恢复演练；Phase 8 交付真实域名接入（tiyoujie.pxcore.com.cn）与一键发布：Caddy 自动签发证书、应用只绑回环、发布失败自动回滚、CI 覆盖生产配置静态校验。后端 203 项测试、Caddy 2.10 边缘层本机演练、生产编排合并与 `check --deploy` 均通过。**整体 PARTIAL：真实证书签发、真实主机发布、微信 AppSecret/真机与题库许可仍未验收，公开发布 NO GO；可上线范围仅限人工错题、题单、复习与导出。**

## 阅读入口

| 内容 | 文档 |
| --- | --- |
| 发布门禁与状态 | [发布门禁](docs/acceptance/release-gates.md) |
| 发布结论、证据与阻断 | [发布报告](docs/acceptance/release-report.md) |
| 上线前三步人工动作（DNS/SSH/AppSecret） | [人工步骤手册](docs/operations/go-live-manual-steps.md) |
| 真实域名上线（DNS/TLS/一键发布） | [上线手册](docs/operations/phase-8-deployment-pxcore.md) · [域名与 TLS](docs/operations/tls-and-domain.md) · [Phase 8 报告](docs/acceptance/phase-8-report.md) |
| 备份恢复、部署与回滚 | [Phase 7 报告](docs/acceptance/phase-7-report.md) · [运维手册](docs/operations/phase-7-deployment.md) |
| 题单、复习与导出 | [Phase 6 报告](docs/acceptance/phase-6-report.md) · [API](docs/api/phase-6-api.md) · [运维](docs/operations/phase-6-operations.md) |
| 题库、核验与变式 | [Phase 5 报告](docs/acceptance/phase-5-report.md) · [ADR-0009 复习与导出](docs/architecture/adr/0009-phase6-review-and-export.md) |
| 分析、提示与修订 | [Phase 4 报告](docs/acceptance/phase-4-report.md) · [Phase 4 API](docs/api/phase-4-api.md) |
| 私图与 OCR | [Phase 3 API](docs/api/phase-3-api.md) · [Phase 3 运维](docs/operations/phase-3-operations.md) |
| 微信小程序构建与导入 | [微信开发说明](docs/development/wechat-development.md) |
| 身份、家庭与权益 | [Phase 2 API](docs/api/phase-2-api.md) · [Phase 2 运维](docs/operations/phase-2-operations.md) |
| 本地开发与测试 | [本地开发手册](docs/development/local-development.md) |
| 需求、差异与阶段计划 | [需求与差异](docs/development/requirements-and-conflicts.md) · [阶段计划](docs/development/phase-plan.md) |
| 架构、数据模型与 ADR | [架构概览](docs/architecture/architecture-overview.md) · [数据模型](docs/architecture/data-model.md) · [ADR 索引](docs/architecture/adr/README.md) |
| 安全与风险 | [威胁模型](docs/security/threat-model.md) · [依赖审计](docs/security/dependency-audit-2026-10-24.md) · [风险清单](docs/development/risk-register.md) |
| OCR 基准 | [OCR 基准工具](docs/quality/ocr-benchmark.md) |

## 开发边界

已建立 uni-app / Vue 3 / TypeScript、Django / DRF、PostgreSQL、Celery / Redis 骨架，依赖锁文件及镜像摘要随仓库提供。数据卷默认私有，数据库/Redis 不发布宿主端口，API 只绑定本地 127.0.0.1。版本选择与兼容范围见 ADR-0002 及 Phase 1 补充 ADR。

平台 AI 体验、用户自带 API（BYOK）和六个月平台功能权益分别管理。平台 AI 默认关闭，只有配额、价格、预算、服务端凭证和告知记录均有效才允许调用。首版不实现支付或自动续费。

## 本地运行

需要 Docker（Linux 容器）、Python 3.12、uv 0.13.1、Node 22。

```powershell
py -3.12 scripts/bootstrap.py
py -3.12 scripts/project.py build
py -3.12 scripts/project.py migrate
py -3.12 scripts/project.py up
```

普通启动不启用测试登录。首次使用需显式配置基础限额；需要本机测试登录时使用 `project.py up --dev-login`，见本地开发手册。在 frontend 目录执行 `npm ci`、`npm run dev:h5`，打开 [本地档案页](http://127.0.0.1:15173/)。API 健康检查为 [readiness](http://127.0.0.1:18000/api/v1/health/ready/)。

## 下一步
真实 OCR/分析仍需合法凭证、条款、样本、价格上界和质量验收；微信联网需合法 HTTPS 后端及服务端 AppSecret。上线前还需目标主机、域名与 TLS。未提交或推送 Git、未部署云端、未创建生效活动。备份恢复演练为单机隔离容器同版本恢复，异机与生产规模恢复仍待演练。

## 许可

本仓库公开用于协作、审计与学习参考，**未授予商用许可**，版权归作者所有。如需二次分发或商业使用，请先联系维护者。

安全问题请按 [SECURITY.md](SECURITY.md) 私下上报。
