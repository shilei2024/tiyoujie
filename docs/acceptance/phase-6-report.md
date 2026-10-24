# Phase 6 开发与验收报告

日期：2026-10-24。目录：D:/cursor-project/tiyoujie。**本轮交付题单、作答、间隔复习、趋势与基础导出。后端 193 项测试、双端构建与真实 HTTP 冒烟通过；真实题库/供应商、界面交互、PDF 与恢复演练仍是缺口，公开发布仍为 NO GO。**

## 1. 本轮交付

| 能力 | 实现 | 边界 |
| --- | --- | --- |
| 题单 | 创建/删除、加入错题、错题快照、题号自动重排、30 题上限 | 监护人管理；学生只能练习 |
| 作答 | 自评 + 结构化算式自动核验、单题 20 次、时长可选 | 不伪装 AI 判卷；`unsure` 不计对错 |
| 间隔复习 | 1/3/7/14/30/60/120 天阶梯、答错回到 1 天、本地日历日 | 确定性算法，不调用模型 |
| 复习队列 | 今日到期 + 新错题、逾天天数、阶段统计 | 单次最多 20 条 |
| 趋势 | 8 周分桶、知识点作答与正确率、样本不足标记 | 总样本 < 10 不给正确率结论；单知识点 < 5 次不显示比例 |
| 导出 | 渲染时生成 HTML/CSV（`?file=csv`），10 分钟票据、可撤销 | 无服务器文件；小程序内不下载，家长端 H5 使用 |
| 数据完整性 | 题单快照、作答、复习事件、票据不可覆写（数据库触发器） | 账号注销仍可级联删除 |

新增 `apps/practice`（模型、服务、视图、Celery 清理任务）、`PRACTICE_TIME_ZONE`、3 个前端页面与 2 个首页入口。设计取舍见 [ADR-0009](../architecture/adr/0009-phase6-review-and-export.md)，接口见 [Phase 6 API](../api/phase-6-api.md)，运维见 [Phase 6 运维](../operations/phase-6-operations.md)。

## 2. 实际测试

| 检查 / 命令 | 结果与范围 |
| --- | --- |
| `project.py test` | **193 通过、0 失败、0 跳过**，隔离 PostgreSQL + 真实 Redis/Worker，12.8 秒；`backend/tests/test_phase6.py` 新增 30 项 |
| 真实队列探针 | PASS：非 eager 任务 `a91c6cad…` 由 Linux Worker 完成；OCR/分析禁止外发探针仍为 `OCR_DISABLED` / `AI_DISABLED`，`sent_at=NULL` |
| `project.py check` | PASS：系统检查 0 issues；无待生成迁移 |
| 迁移 | 新增 practice `0001_initial`、`0002_practice_guards`，开发卷增量升级成功 |
| 真实本地 HTTP 冒烟 | PASS：见 `artifacts/phase6-http-smoke.json` |
| Ruff check / format --check | PASS（practice + 测试文件） |
| 前端 type-check / format:check | PASS |
| build:h5 / build:mp-weixin | PASS |
| npm audit / pip-audit | PASS：npm 0 漏洞（info/low/moderate/high/critical 均为 0），pip-audit 退出 0、66 个依赖无已知漏洞 |
| 新页面交互 / 模拟器 / 真机 | **NOT TESTED**：本轮未做浏览器或模拟器操作；仅构建与接口验证 |

### 真实 HTTP 冒烟摘要（`artifacts/phase6-http-smoke.json`）

```
worksheet_http 201 · item_answer_hidden true · attempt_http 201
review_due_on 2026-10-25 · queue_due 0 · trend_sample_sufficient false
export_html_bytes 1389 · export_csv_bom true · deleted_export_http 410
account_cleanup_worker succeeded · test_identity true
```

冒烟使用随机测试身份与真实注销接口，Worker 完成清理后旧令牌返回 401；未删除其他账号或开发数据。

## 3. 与门禁相关的验证

- **越权**：跨家庭题单/趋势/导出返回 404；学生无授权 404、有授权仅能作答；监护人独占管理与导出。
- **答案泄露**：创建题项与列表接口不返回答案；学生需先作答或由监护人请求才可见。
- **来源撤回**：题库限制到期或修订变化后，题项 `source_available=false`，文本隐藏，作答返回 409。
- **删除语义**：题单删除后详情 404、既有导出票据 410；错题删除级联移除题单项与复习计划。
- **导出安全**：HTML 无任何 `http://`/`https://` 外链，CSP `default-src 'none'`，动态内容全部转义；CSV 带 BOM 且对 `= + - @` 开头单元格加 `'` 前缀。
- **不可变**：直接 UPDATE 作答、题单快照、复习事件、票据身份均被数据库拒绝（`23514`）。
- **统计诚实**：1 次作答时 `sufficient=false`，知识点正确率为 `null`；达到阈值后按实际数据计算。

## 4. 未完成与阻断

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 真实题库许可与审核（G08） | BLOCKED | 无授权题目与审核人 |
| 真实 OCR / 分析质量（G07/G09） | BLOCKED | 无合法凭证与授权样本 |
| 微信登录、真机、模拟器交互（G12） | BLOCKED / NOT TESTED | 缺 AppSecret、合法 HTTPS 域名；本轮未做界面操作 |
| PDF 二进制导出 | NOT IMPLEMENTED | 无 PDF 依赖；以 HTML 打印替代，待 Phase 7 评估 |
| 备份恢复与发布演练（G11/G14） | NOT TESTED | 尚未实施 Phase 7 |

## 5. 收尾

未部署、未提交或推送 Git、未创建生效活动、未调用真实供应商。测试环境以外的开发数据未改动；开发卷与主密钥保留。构建产物、审计 JSON、测试日志与冒烟摘要均保存在 `artifacts/`。
