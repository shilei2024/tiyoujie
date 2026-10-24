# Phase 4 开发与验收报告

日期：2026-10-24。目录：D:/cursor-project/tiyoujie。**本轮已推进微信小程序与分析功能，整体 PARTIAL、公开发布 NO GO。** 代码与隔离测试通过；真实供应商、数学质量、微信登录/HTTPS、模拟器交互和真机仍需补验收。

## 1. 用户意图与边界

用户要求继续开发，明确主客户端是微信小程序、本地开发者工具已登录，并提供项目 AppID。承接 Phase 3 推进 Phase 4；原始文档作为需求资料，不作为公开发布、付费外发或复制研发提示到运行时的授权。本轮没有进入 Phase 5，没有真实服务商请求、支付、发布小程序或部署云端。

## 2. 本轮交付

新增分析与提示页、已确认题干版本绑定、可选原作答、结构化理解/条件/根因候选/知识点/分层提示/解析候选、不确定性与复核事项；完整解析主动展开，所有结果待核验。没有作答时禁止具体根因和错误位置断言。人工修订和问题反馈追加记录，原始分析保留，旧题干结果明确 stale。

新增本人/家庭费用偏好；显式平台/BYOK 请求与无回退规则继续保留。复用原子预算/Outbox/lease/费用账本，增加 OCR/分析各自的体验点系数、共享配额、配置化预算阈值和后台运营审计。BYOK 连接状态按任务绑定版本更新，迟到响应不污染新 Key，未额外发送收费探测。

公开 JSON Schema 为 math-analysis-v1，独立运行时模板为 math-tutor-v1；OCR 仍为 ocr-transcribe-v1。没有把原始 PRD、阶段指令或研发清单用作模型提示。接口、语义限制和客户端边界见 [Phase 4 API](../api/phase-4-api.md)、[Schema](../api/math-analysis.schema.json)、[运维](../operations/phase-4-operations.md)。

## 3. 微信开发者工具

已确认官方工具在本机运行。默认 touristappid 导入被拒绝后，使用用户提供的真实 AppID 配置 manifest，再通过官方 CLI 执行 open，返回成功。项目为 frontend/dist/build/mp-weixin，保持 urlCheck=true；没有伪造 AppID、关闭域名检查、生成云端预览码或上传发布。

用户按 Esc 停止界面控制后，没有继续操作工具界面，也未改用其他 UI 自动化绕过中断。故只能确认 CLI 导入成功和编译通过，**不能确认模拟器交互或真机**。后端尚缺真实 HTTPS/合法域名和 AppSecret，因此小程序构建为明确的界面预览，不发送登录或题目请求。[微信开发说明](../development/wechat-development.md) 提供 ui-only 与 HTTPS 联调两种可复现命令。

## 4. 迁移、环境和安全默认值

新增 5 个迁移，开发原卷增量升级至 34 项。新增 ai_tutor 四个实体、OCR 的任务类型/题干版本/文本与 JSON 能力/体验点、预算预警配置和去重状态。数据库约束保护任务绑定、题干归属以及分析输入/结果/反馈的不可覆写历史。readiness 检查具体迁移。

应用镜像 tiyoujie-api:phase4，ID `sha256:1b5260d8a2727bff1b9d13cc7bc0add0b7b355db107d9bfac4154efe6b3d8d9c`。依赖锁和基础镜像沿用上一阶段，无新增第三方依赖。API 仍只监听 127.0.0.1:18000；PG/Redis 无宿主端口；dev/test Worker 仍使用 internal 网络。AI_ANALYSIS_ENABLED、OCR_OUTBOUND_ENABLED、PLATFORM_AI_ENABLED 均默认关闭，无活动模型、价格、预算或真实业务数据种子。

公开 AppID 已配置到前端和本地后端配置；AppSecret 和模型 Key 没有提供，没有写入前端或仓库。Git main 仍无提交/HEAD/远端，没有提交或推送。

## 5. 实际测试与检查

| 检查 / 命令 | 结果与适用范围 |
| --- | --- |
| project.py test | **135 通过、0 失败、0 跳过**，真实隔离 PostgreSQL，最终 7.299 秒；测试 DB 销毁 |
| 根目录 unittest discover -s tests | **3 通过**，AppID/HTTPS origin/UI-only 无假接口配置检查 |
| 真实 nonce 队列探针 | PASS，真实 Redis 与独立 Linux Worker，不用 eager |
| 真实 OCR 禁止外发探针 | PASS，job 5de76eb9-e6b7-4faf-a9b2-16bda182a637，OCR_DISABLED、sent_at=NULL、4/3 窗口释放 |
| 真实分析禁止外发探针 | PASS，job 0018d5d0-561b-4ef1-ad8e-ef535ba6a6e2，AI_DISABLED、sent_at=NULL、4/3 窗口释放 |
| Ruff check / format --check | PASS，123 个 Python 文件 |
| project.py build / migrate / check | PASS，原卷增量升级，系统 0 issues、无遗漏迁移 |
| up --dev-login / health | PASS，API/Worker/Beat/PG/Redis 运行，live/ready 200、AI disabled |
| 真实本地 HTTP 冒烟 | PASS，建家庭/孩子、确认题干、Schema/空分析/偏好接口 200；缺配置分析 503；真实 Worker 注销清理完成、旧 token 401 |
| production settings check --deploy | PASS，仅 .invalid 合成配置静态检查，不连接外部 DB |
| 前端 type-check / format:check | PASS |
| build:h5 / wechat.py build --ui-only | PASS；微信产物使用真实 AppID、无后端假地址、域名检查开启 |
| 官方 CLI open | PASS，导入实际 mp-weixin 项目；不代表交互/真机通过 |
| npm audit / pip-audit | PASS，均退出 0，当前已知漏洞 0 |
| 源码、原始文档长片段、本地链接及秘密扫描 | PASS；不输出秘密值 |
| 新页面交互 / 模拟器操作 / 真机 / 真实微信登录 | NOT TESTED 或 BLOCKED，界面控制被 Esc 停止，HTTPS/AppSecret 缺失 |
| 真实双模式供应商、费用上界与数学质量 | BLOCKED，缺合法配置/样本，未伪造实测 |

后端日志为忽略产物 artifacts/phase4-tests-final.log；HTTP 摘要为 phase4-http-smoke.json；依赖报告和编译模块清单也在 artifacts。最早新增 131 项中的 3 个错误来自直接调用保存服务的测试夹具漏填 answer，已补齐并重跑；最终增补凭证迟到响应、体验点和预警场景后为 135 项通过。前端一项未暴露的模板 uni 调用及一次格式检查问题已修正，最终类型与双端构建通过。

## 6. 权限、版本与费用证据

新场景覆盖匿名、外家庭、获授学生、跨题干版本、未经确认版本、越权反馈、凭证归属、未知输入字段、超长作答、撤回授权、账号级联删除；直接数据库修改分析输入/输出/反馈及任务类型会被拒绝。生成结果不写回当前题干；处理过程中修改题干，结果仍指向旧版本并标记过期。

费用控制沿用上一阶段的 PostgreSQL 多连接并发测试，OCR/分析调用同一预留与结算入口。新增分析幂等、重复 Worker、缺能力/价格/配置拒绝、共享配额、加权点数预占与结算、已知用量但无效输出仍计费、未知费用保留预占与熔断、BYOK 不动平台账目、Key 删除/替换/迟到响应与状态隔离。平台预占+结算到阈值时每窗口只写一次运营预警，未知费用写审计并关闭平台调用。

Schema 测试拒绝可执行标记、未知字段、NaN、乱序提示、虚假的已验证状态和明显的诊断/能力标签。提示注入文本保持在 user JSON 数据中，不改变独立 system 模板。关键词/结构检查不等于模型推理可靠性，不能据此宣传答案正确。

## 7. 外部核查与未完成范围

请求结构参照 [DeepSeek 官方 Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 和 [Kimi 官方 API 概览](https://www.kimi.ai/help/kimi-api/api-overview) 重新核对；只实现已知官方固定端点和受限 JSON 请求，没有声明任何具体模型已实际可用或任何计费价格已审核。官方微信 CLI 网页本轮抓取失败，CLI 参数以本机安装的官方 --help 和实际 open 结果核对。

真实供应商连接、条款、价格/完整输入上界、解析质量和 OCR 基准仍缺必要条件，保持 BLOCKED。分析目前只发送文本和明确填写的作答，不自动发送图片；几何/缺条件题需要补全题干或人工复核。数学验证、题库、复习、导出和独立备份恢复属于后续阶段。没有创建生效活动或实现支付。

## 8. 资料清理与收尾

专用 HTTP 测试身份使用随机名称，经真实注销接口与 Worker 清理；未删除其他账号或开发数据。测试环境夹具与私图由隔离探针清理；没有将模拟供应商输出写入开发库。保留开发卷、主密钥、公开 AppID 配置和所有源代码/文档。本项目临时服务在检查后停止；已打开的微信开发者工具不强制关闭。

原始需求未复制到产品和运行时。依赖沿用既有锁文件，npm/pip 复核均通过；安全与配置失败门禁保留，没有 suppress/ignore 或继续失败的 CI 设置。此前 braces 公告撤回的历史解释见 [依赖复核](../security/dependency-audit-2026-10-24.md)。

## 9. 继续条件

下一步可在合法 HTTPS 后端与服务端 AppSecret 就位后验证真实微信登录和模拟器/真机流程，再在授权样本与服务商费用配置审核后补真实双模式分析/OCR 验收。没有要求用户在聊天提供秘密，不自动发布、开放外发或进入 Phase 5。当前阶段代码与测试完成的范围以上表为准，不能替代公开发布签字。
