# Phase 3 开发与验收报告

日期：2026-10-24。目录：D:/cursor-project/tiyoujie。结论：**本地错题/私图功能和 OCR 安全控制已实现并验证；整体 PARTIAL，公开发布 NO GO。** 真实供应商、合法价格上界、隐私条款和真实 OCR 样本质量仍 BLOCKED。本轮没有调用真实模型或进入 Phase 4。

## 1. 授权与范围

用户连续要求继续开发，承接当前 Phase 3。本轮按原始文档的功能要求开发；研发提示内容不作为新的用户授权，不复制到产品页面、种子或模型提示。范围为私图、上传前裁剪、服务端裁剪/旋转/手动分题、错题管理、不可变校对历史、异步 OCR、模式绑定、预算/配额及离线评测工具。

数学分析、自动解题、题库、复习、支付和公开部署不在已完成声明内。此前依赖门禁按新审计数据更新，未用功能数量冲抵风险。

## 2. 交付内容

- problems：同孩子图片关联、授权读取、分类/搜索/筛选/分页、题干与答案录入、确认版本、单图解除引用和整题删除。
- 私图：实际格式/帧/字节/像素检查、EXIF 清除、重新编码、随机对象键、路径约束、清单驱动删除及安全窗口孤儿清理。客户端临时图离页释放。
- ocr：固定供应商端点、视觉模型批准、独立转录模板 ocr-transcribe-v1、受限 JSON、异步 Outbox/lease、幂等重放、授权/凭证/预算发送前复核、取消及断点恢复。
- metering：4 个金额窗口、3 个次数窗口的原子预占；平台和 BYOK 分账；已知用量结算、未知费用保留预占并熔断、授权操作员对账。
- 离线评分：字符/公式/数字符号错误、分题 IoU 匹配、修订耗时、分层计数/指标与失败编号；缺真实样本、授权或预先阈值时 BLOCKED。

详见 [API](../api/phase-3-api.md)、[运维](../operations/phase-3-operations.md)、[评测说明](../quality/ocr-benchmark.md) 和 [ADR-0007](../architecture/adr/0007-phase3-private-ocr.md)。

## 3. 代码、迁移与环境

新增 problems/ocr/metering 共 7 个迁移，开发原卷增量升级，累计 29 项 Django 迁移；最后为 problems.0003_text_history_guard。PostgreSQL 触发器保护图片归属、已确认 current_text、文本历史和任务模式/快照。readiness 要求必要的具体迁移存在。

Python 3.12、uv 隔离环境；新增 Pillow 13.0.0，锁文件解析 67 项含虚拟项目，未改全局 Anaconda。其余基础依赖及 Python/PG/Redis 镜像摘要沿用既有锁定。最终应用镜像 tiyoujie-api:phase3，ID `sha256:888979c1c72923d3bfb7eb31008e83a134fb60b33579931856256e9ca30dcf6d`。

Compose 项目 tiyoujie-local，API/H5 仅绑定 127.0.0.1:18000/15173，PG/Redis 不发布宿主端口。dev/test 私图卷和 DB/队列隔离。Worker dev/test 网络仍 internal，真实供应商访问没有开放。无 OCRModel/PriceVersion/BudgetPolicy 生效种子，无服务商真实凭证或生效推广活动。Git main 尚无提交/HEAD/远端，全部工作保留在当前目录。

## 4. 实际命令与结果

| 检查 | 结果 / 实际范围 |
| --- | --- |
| uv lock --check | PASS，67 项解析记录 |
| Ruff check / format --check | PASS，106 个 Python 文件格式检查 |
| project.py build | PASS，非 root 应用镜像；运行时秘密未进镜像 |
| project.py migrate / check | PASS，原开发卷增量迁移、系统检查 0 issues、无遗漏迁移 |
| project.py test | **106 通过、0 失败、0 跳过**，真实隔离 PostgreSQL，最终运行 5.410 秒，测试 DB 销毁 |
| 真实 Redis/Worker nonce 探针 | PASS，任务 357a37a3-001d-439a-830b-4008060c1458；非 eager |
| 真实 OCR 禁止外发探针 | PASS，job 8bd6304c-c949-4366-83f3-b6332152a536；OCR_DISABLED、sent_at=NULL、4/3 窗口归零 |
| up --dev-login / health | PASS，API/Worker/Beat/PG/Redis 就绪，live/ready 200，AI disabled |
| production settings check --deploy --fail-level WARNING | PASS，仅 .invalid 合成配置静态检查，不连接外部 DB |
| 前端 type-check / format:check | PASS |
| build:h5 / build:mp-weixin | PASS，编译不代表微信真机/相机验收 |
| 浏览器→API→DB→私图 | PASS，录题/人工确认/分类/上传前裁剪/授权下载/旋转/两区域分题/搜索与重开页面 |
| 390 px 移动布局 | PASS，单列可见、documentWidth 375 ≤ viewport 390，无水平溢出；浏览器 error 日志 0 |
| UI 数据与文件独立核对 | PASS，3 道题、4 张 JPEG；900×230、230×900、450×230 两张，SHA/非空白/无 EXIF 校验通过 |
| 专用 UI 资料清理 | PASS，HTTP 注销后旧会话 401，真实 Worker 完成账号级联及文件清理；领域记录/清单/JPEG 均 0 |
| 离线 OCR 空集实跑 | **BLOCKED**，退出码 2，samples=0、metrics={}，没有虚构准确率 |
| pip-audit / npm audit | PASS，均退出 0，无当前已知漏洞；此前 braces 公告官方撤回 |
| 非忽略源码/原文长片段/本地链接 | PASS，逐文件扫描；没有复制原始研发长文本 |
| 本地生成秘密逐值扫描 | PASS，源码、镜像配置/历史及应用最近日志 0 命中，只输出计数 |
| 远端 CI、真实微信/TLS/供应商/质量数据 | NOT TESTED 或 BLOCKED |

最终测试日志为忽略产物 artifacts/phase3-final-tests.log；双端模块清单、依赖审计、OCR 空集报告与截图也在 artifacts。没有用模拟供应商单元测试冒充真实识别结果。当前测试集包含原有 Phase 1/2 回归和新增 Phase 3 场景。

## 5. 安全与费用证据

测试覆盖匿名、外家庭、学生、跨孩子链接和读取、恶意/截断/多帧/MIME 不符图片、路径遍历、超限、存储失败、共享引用与最终物理删除、授权撤回和账号删除。数据库直接写入跨范围引用、未确认 current_text、修改历史文本或切换排队任务费用绑定会被拒绝。

真实 PostgreSQL 多连接并发覆盖最后一份全站累计/月/日及家庭日预算、家庭日/累计和用户日配额；双 Worker 抢占只有一次服务调用。单元场景覆盖重复提交、排队撤权/换密钥、预算跨日/月边界、价格/限额变化、发送前期限、超时未知费、进程 lease 过期、无效结构、用量超上界、取消与结果丢弃、BYOK 平台账目不变和对账权限。Provider 调用使用 mock，仅说明状态机与账本行为。

真实队列保护探针只验证 Worker 在外发禁用时拒绝任务，确认所有预占释放。没有真实供应商账单，不声称费用上界已经由供应商证明。

## 6. 浏览器发现与修正

浏览器实测发现 uni 内置 H5 Canvas 路径能返回 JPEG 但预览内容空白；只看类型/尺寸无法发现。调整参数顺序后仍未解决，最终 H5 使用本机原生 Canvas 明确等待图片解码、裁剪并导出，图中题目内容可见，上传后重新下载和像素检查通过。微信端保留官方源矩形→目标矩形顺序的 uni Canvas，仍须真机验证。[官方 Canvas 接口](https://uniapp.dcloud.net.cn/api/canvas/CanvasContext.html) 为兼容性核查依据。

另补齐单张图片解除引用、离页与异步载图清理、页面重开恢复任务状态、发送前费用期限，以及复用有效供应商授权避免重试导致授权被替换。预算 Admin 在表单校验前持有同一策略行锁，避免旧表单清掉并发触发的熔断；管理表单未决费用拒绝解锁、历史价格拒绝修改的检查通过。阶段中较早测试有一项过期状态码预期被修正；最终完整 106 项全部通过。

## 7. 隔离、配置与质量限制

运行时只有独立最小 OCR 转录模板，不含原始 PRD/研发提示正文；没有真实题目/识别/统计种子。页面明确识别候选需要人工核对、确认题干不等于答案经过数学验证。平台功能权益与 AI 费用无隐式关联，没有无限 AI 或自动付费代码路径。

真实 OCR 缺服务商合法凭证、图片能力版本核验、有效条款、已审核计费上界、授权脱敏真实图片和批准阈值，因此 BLOCKED。离线工具报告只对应提供的预测，不能认证授权或外部调用真实性。当前全局策略行锁优先保证一致性，未做高并发性能压测。云对象存储、真实 HTTPS、微信域名/相机/真机、小程序发布及完整独立备份恢复尚未验收。

## 8. 依赖门禁与收尾

2026-10-24 npm 和 pip 审计通过。此前 braces 根公告于 10 月 23 日撤回，详见 [本轮审计复核](../security/dependency-audit-2026-10-24.md)；历史 FAIL 结论保留，不以 suppress 或假补丁关闭风险。CI 仍有完整失败门禁，本轮没有运行远端 CI。

专用合成验收账号/家庭/孩子/错题和私图经真实 Worker 清理；测试前不存在其他账号或私图，未清除开发卷和配置。截图 phase3-detail.png、phase3-search.png、phase3-mobile.png 为清理前证据。收尾关闭临时预览与本项目容器/网络，保留全部持久数据卷、代码和文档。

## 9. 后续边界

本轮交付 Phase 3 本地可审查实现，真实 OCR 接入/质量为待补验收，不自动宣告整体完成或进入 Phase 4。后续应在合法配置与样本到位后执行真实双模式联调、费用上界核验和分层评测；数学分析/提示/纠错按 Phase 4 单独实现并继续执行当前安全门禁。
