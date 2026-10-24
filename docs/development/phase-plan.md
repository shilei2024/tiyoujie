# 分阶段开发与验收计划

日期：2026-10-22。阶段采用工程 0–8，映射和冲突见 [ADR-0001](../architecture/adr/0001-scope-and-conflicts.md)。每轮交付只进入当前阶段；失败门禁先修复，不能用后续功能数量补偿。

## Phase 0：本轮设计交付

产物：环境盘点、P0/P1/P2、差异记录、架构/部署/数据流、实体关系/API/页面清单、版本/Provider 核查、混合费用/权益 ADR、威胁模型、风险和发布门禁。设计检查 PASS 不等于 PRD 的真实接入原型已通过。详见 [阶段报告](../acceptance/phase-0-report.md)。

## Phase 1：最小基础设施交付

2026-10-22 实施状态：Phase 1 功能验证完成，依赖安全退出条件 P1-08 仍失败，整体 PARTIAL，详见 [历史报告](../acceptance/phase-1-report.md)。随后用户明确要求继续，本地 Phase 2 已实施，边界见 [ADR-0006](../architecture/adr/0006-phase2-local-continuation.md)。

目标：从干净克隆能安装、构建并启动**空业务骨架**，健康检查和独立数据库测试真实通过。不需要生产凭证、OCR 样本或服务器登录。

按依赖顺序实施：

1. 在当前工作目录初始化本地 Git（若用户之后已建库则复用），保留所有文档，不自动提交/推送。创建 frontend、backend、worker、infra、tests；先声明 dev/test/staging/prod 边界。
2. 核对 ADR-0002 候选与安全支持。隔离 Python 3.12、生成 uv.lock；官方 uni-app 正式 Vue3 TS 模板固定 commit，审查并解决依赖安全/兼容性，保留必要目标，生成 package-lock.json。
3. Django/DRF 只提供 `/api/v1/health/live/` 和 `/api/v1/health/ready/`。live 表示进程；ready 检查专用 DB/Redis 和必要结构，失败返回 503，不暴露 DSN/秘密。AI 未配置不影响基础设施 ready，但 AI 状态明确 disabled。
4. 建立无业务权限的 Celery 入口和仅测试使用的任务；验证真实 Redis 入队与 Worker 接收，不用 eager 模式代替队列验收。Worker 复用 backend 镜像。
5. 前端只有非演示的基础壳/服务状态/错误态，能构建 H5 和 mp-weixin，不填假错题/识别结果/学习统计，不实现实际登录、凭证页或收费调用。
6. 新建 `.gitignore`、`.env.example`（全为空值或显式无效占位）、配置验证、结构化允许字段日志、格式检查/类型检查、pre-commit、Linux CI。实际 .env、私有 media、备份和 token 均忽略；禁止在仓库模板填真实秘密。
7. 创建独立 Compose 项目和网络/卷，PG/Redis 不对公网开放，应用本地绑定 127.0.0.1。容器标签与 digest 可追踪，启动不自动灌演示数据。测试 profile 独立 DB/存储和 DB 用户，不使用宿主机现有数据库。
8. 显式迁移，配置检查、安全检查、API/依赖故障/健康测试、前端类型和双端构建、镜像 build/up/health、真实队列验证，保存真实命令/结果到验收报告并更新运维文档。

### Phase 1 退出标准

| ID | 必须真实通过 | 证据 |
| --- | --- | --- |
| P1-01 | 新环境依赖按锁文件安装 | `uv sync --frozen`、`npm ci` 日志，记录版本/镜像 digest |
| P1-02 | Django 配置、迁移/无待生成迁移 | `manage.py check`、`makemigrations --check --dry-run`、独立 DB migrate |
| P1-03 | live 200、ready 正常 200/依赖失败 503 | API 测试，独立 DB，日志无 DSN/秘密 |
| P1-04 | Redis 入队、Linux Worker 完成测试任务 | 真队列结果与任务 ID；单元 fake 不算此项 |
| P1-05 | H5、mp-weixin 构建和 TypeScript 检查 | 退出码/产物；微信真机仍单列未验证 |
| P1-06 | Compose build/up 和全部必要健康状态 | 实际容器结果；不能只通过 compose config |
| P1-07 | dev/test/production 分离，生产拒绝空强制秘密 | 配置正反测试，无生产 DB/文件接触 |
| P1-08 | 秘密/研发内容隔离和依赖漏洞门禁 | 全量受控扫描；风险不能以模板自带为由忽略 |

不在该阶段实现 Family/Problem/AI/权益领域模型、不发真实 Provider 请求、不部署生产、不创建生效推广活动。不把 health 成功称为产品闭环。

## 后续阶段

Phase 2/3 的历史结果见 [Phase 2 报告](../acceptance/phase-2-report.md)、[Phase 3 报告](../acceptance/phase-3-report.md)。后续推进：[Phase 4](../acceptance/phase-4-report.md) 分析/提示/费用保护；[Phase 5](../acceptance/phase-5-report.md) 题库导入、权利审核、数学核验与变式草稿；[Phase 6](../acceptance/phase-6-report.md) 题单、作答、间隔复习、趋势与导出；[Phase 7](../acceptance/phase-7-report.md) 备份恢复演练、生产编排与回滚手册。当前 203 项后端测试、双端构建、依赖审计与本地隔离恢复演练通过；Phase 8 补齐真实域名接入（Caddy 自动签发）与一键发布/回滚。真实 AI/OCR、题库许可、微信 AppSecret/真机与目标主机执行仍待验收。

| 阶段 | 最小可交付 | 强制退出证据 | 外部依赖 |
| --- | --- | --- | --- |
| 2 | 身份/家庭/孩子/授权、凭证加密与掩码、活动/权益/Admin | 对象矩阵、月底闰年/重复资格/到期保留、轮换/删除；迁移 | 微信真实配置；本地 adapter 只能 dev 且标注 |
| 3 | 私图、裁剪/分题、异步 OCR、校对、错题 CRUD | 上传恶意样本、版本/关联/删除、平台原子预算与 BYOK 绑定、OCR 基准工具 | 授权脱敏图片、OCR 凭证/有效价格预算 |
| 4 | AI Schema、分析/提示/纠错、双模式调用与分账 | 并发预算/日月边界/崩溃/超时未知费、真实 Provider、日志扫描 | AI 凭证、告知/政策、模型/价格复核 |
| 5 | 题库最小 JSON 导入、权利审核、检索、验证器、变式草稿 | 缺许可隔离、答案正反/边界、不支持不通过 | 有授权的题/答案/解析与审核角色 |
| 6 | 题单/作答、间隔复习、趋势、基础导出（HTML/CSV）与删除 | 样本不足、算法、导出权限/渲染、防外网资源、删除后拒绝 | 产品认可统计口径；PDF 待评估 |
| 7 | 安全/全量测试、备份恢复演练、生产编排与回滚手册 | 漏洞/秘密/越权、DB+文件恢复、回滚 | 目标服务器/域名/TLS/存储/微信/责任人 |
| 8 | 门禁证据审查、release-report 和负责人签字 | PASS/FAIL/BLOCKED/NOT TESTED，无关键缺口 | 产品负责人和责任主体确认 |

Phase 5/6/7 的交付状态分别见对应报告；Phase 6 以渲染时生成 HTML/CSV 替代 PDF 二进制，理由见 ADR-0009。Phase 8 只有在真实环境与外部依赖关闭后才可签字，当前不生成“已发布”结论。

Phase 3 是首个平台付费 OCR 入口，因此 metering 的预留、价格/预算 fail closed、模式绑定必须在 Phase 3 前完成相关实现与测试，不能拖到 Phase 4 后补。

## 质量口径

测试使用独立 PG 与临时文件，禁止生产 DB；fake 仅用于隔离单元测试。报告通过/失败/跳过实际数，不把未运行记通过。没有真实图片可交付 OCR 代码但质量门禁 BLOCKED。没有真实 Provider 可验收架构单元规则，但真实接入仍 BLOCKED。自动化通过、受控试用、正式公开发布是三个结论。

运行时模板按首次功能入口创建。Phase 3 已登记独立转录模板 ocr-transcribe-v1，仅识别题面并返回受限 JSON；Phase 4 的分析/提示/纠错模板尚未实现。禁止把研发说明作为模板正文。

用户再次要求继续并提供微信 AppID 后已推进 Phase 4，见 [Phase 4 报告](../acceptance/phase-4-report.md)。本轮实现分析、提示、修订、模式偏好和费用保护；真实 OCR/分析、微信联网与真机仍待验收。未自动进入 Phase 5，不把阶段报告视为公开发布授权。
