# 发布报告（Phase 8 证据汇总）

日期：2026-10-24。目录：D:/cursor-project/tiyoujie。**结论：公开发布 NO GO；人工错题最小范围在具备真实主机、域名/TLS 与微信 AppSecret 后可上线，平台 AI/OCR 与题库推荐必须保持关闭。**

本文件是证据汇总，不是发布签字。产品负责人与责任主体确认前，不得对外宣传“已上线”“可识别”“答案可信”。

## 1. 版本与环境

| 项 | 值 |
| --- | --- |
| 代码版本 | 工作树（尚无 Git 提交；**部署前必须建立可追溯 commit，否则不得发布**） |
| 后端镜像 | `tiyoujie-api:phase7` · `sha256:53b007162bfc09962374f2e2ae3637af440631059bca3727f74e027e40ba746e` |
| 后端 | Django 5.2.18 / DRF 3.18.3 / Python 3.12 / Celery 5.6.3 |
| 数据 | PostgreSQL 18.6（固定 digest）、Redis 8.2.10（固定 digest） |
| 前端 | uni-app 3.0.0-5020620260917001 / Vue 3.4.21 / TypeScript 5.9.3 |
| 本地环境 | Windows 11 + Docker Desktop，Compose 项目 `tiyoujie-local`，API 仅绑定 127.0.0.1:18000 |
| 目标环境 | 未提供（服务器、域名、TLS、备案均未知） |

## 2. 实际执行的验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量测试 | `py -3.12 scripts/project.py test` | **193 通过、0 失败、0 跳过**，隔离 PostgreSQL + 真实 Redis/Worker，12.1 秒 |
| 真实队列探针 | 同上内置 | PASS：非 eager 任务由 Linux Worker 完成；OCR/分析外发探针 `OCR_DISABLED`/`AI_DISABLED`，`sent_at=NULL` |
| 系统与迁移一致性 | `project.py check` | PASS：0 issues，`makemigrations --check` 无变更 |
| 真实 HTTP 冒烟 | `artifacts/phase6_http_smoke.py` | PASS：题单/作答/复习/趋势/导出/删除后 410/注销清理 |
| 备份恢复演练 | `artifacts/phase7_restore_drill.py` | PASS：备份 0.61s、恢复 0.33s、媒体哈希一致、38 迁移/55 表/18 触发器、测试行与图片恢复、清理成功 |
| 生产配置静态检查 | `manage.py check --deploy`（prod、`.invalid` 主机） | PASS，0 issues；弱 secret、prod dev-login、HTTP origin 三类负例均按预期拒绝 |
| 生产编排合并 | `docker compose -f compose.yaml -f infra/deploy/compose.prod.yaml config --quiet` | PASS（合成占位值，未启动容器） |
| 前端类型与构建 | `npm run type-check` / `build:h5` / `build:mp-weixin` | PASS |
| 依赖审计 | `npm audit` / `pip-audit` | PASS：npm 全等级 0；pip 66 个依赖无已知漏洞 |
| 秘密扫描 | `artifacts/scan_phase4_secrets.py`（已更新至 phase7 镜像） | PASS：239 个未忽略文件 + 镜像 + 近期日志，命中 0 |
| 浏览器/模拟器交互 | — | NOT TESTED（本轮未执行界面操作） |

## 3. 外部证据（必须由责任主体提供）

| 项 | 状态 | 缺失内容 |
| --- | --- | --- |
| OCR 数据集与授权分层 | BLOCKED | 合法脱敏样本、分层阈值、评测报告 |
| OCR/分析供应商实测 | BLOCKED | 合同、价格上界、凭证、告知记录 |
| 题库许可与审核人 | BLOCKED | 授权证明、期限、审核记录 |
| 微信登录与真机 | BLOCKED | AppSecret、合法 HTTPS 域名、真机验收 |
| 目标主机与 TLS | BLOCKED | 服务器、域名、证书、备案 |
| 跨机备份与恢复 | NOT TESTED | 加密异机备份、生产规模、账本/权益重算 |
| 隐私政策与监护人告知 | BLOCKED | 文本、版本号与产品确认 |

## 4. 门禁状态摘要

| 门禁 | 状态 |
| --- | --- |
| G01 权限与跨家庭隔离 | PASS（Phase 2/3/6 范围） |
| G02 图片与删除安全 | PASS（本地）；云存储待验收 |
| G03 BYOK 加密与隔离 | PASS（合成值）；真实 TLS/Provider BLOCKED |
| G04 预算不可绕过 | PASS（并发/边界/故障）；真实价格 BLOCKED |
| G05 模式绑定与分账 | PASS（代码规则）；真实双模式 BLOCKED |
| G06 权益自然月与到期 | PASS |
| G07 OCR 质量 | BLOCKED |
| G08 题库权利与发布审核 | BLOCKED |
| G09 数学可信度 | PASS（受限范围）；真实题库质量 BLOCKED |
| G10 全量测试/构建/审计 | PASS；交互 NOT TESTED |
| G11 独立恢复 | 本地 PASS（有限范围）；异机与账本重算 NOT TESTED |
| G12 微信/TLS/备案/隐私 | BLOCKED |
| G13 研发内容隔离 | PASS |
| G14 部署/回滚/轮换/故障手册 | PARTIAL：已就绪，未在目标主机演练 |

任一关键 BLOCKED 都阻断公开发布，不用 PASS 数量抵消。

## 5. 可上线的范围（建议）

在满足以下全部条件时，可先上线**最小人工范围**：

1. 目标主机就绪，`tiyoujie-api` 以固定 digest 部署，数据库/Redis 不暴露公网。
2. 真实域名 + TLS 证书 + 微信 request 合法域名；AppSecret 仅存服务端。
3. 隐私政策、监护人告知版本与保留期由责任主体确认；`GUARDIAN_NOTICE_VERSION` 与之对应。
4. 建立 Git 提交基线，记录镜像 digest、迁移列表与备份编号。
5. 保持 `AI_ANALYSIS_ENABLED=0`、`OCR_OUTBOUND_ENABLED=0`、`PLATFORM_AI_ENABLED=0`，题库推荐不开放或仅内部试用。

该范围内的能力：家庭/孩子与授权、图片上传与人工核对、错题管理、题单、作答、间隔复习、趋势（样本不足不显示正确率）、导出、删除与注销。

**不得宣称**：自动识别准确率、AI 分析可靠性、题库答案可信度、支付/会员扣费（未实现）。

## 6. 风险例外

| 风险 | 处置 |
| --- | --- |
| 导出文件由用户本地保存 | 导出页脚提示私人内容；系统无法撤回用户已保存文件 |
| 小程序内不支持下载导出 | 明确提示使用家长端 H5；不隐藏该限制 |
| 复习算法不个性化 | 文案注明固定阶梯，不宣称自适应掌握 |
| 无 PDF 二进制 | 以 HTML 打印替代，是否需要 PDF 待产品确认 |

## 7. 决定

- **公开发布：NO GO。**
- **最小人工范围：条件性 GO**，条件见第 5 节；条件未满足前保持本地/内测状态。
- 平台 AI、OCR 外发、题库公开推荐：保持关闭。
- 下一次评审需要：真实环境部署记录、微信真机记录、备份（异机）演练记录、隐私文本确认、负责人签字。
