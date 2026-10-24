# Phase 3 存储、OCR 与费用运维

2026-10-24。当前用于本地开发，不是公开部署说明。先阅读 [Phase 2 运维](phase-2-operations.md) 中的角色、主密钥和删除边界。

## 私有文件和迁移

Phase 3 新增 problems/ocr/metering 共 7 个迁移；`problems.0003_text_history_guard` 为最后一个。开发库从 Phase 2 原卷增量升级，readiness 要求领域迁移和数据库范围/版本约束均存在。升级前备份 DB、私图卷和独立加密主密钥。禁止为了通过 readiness 删除迁移记录或重建数据卷。

API 和 Worker 共享 private_dev，测试使用另一个 private_test；均无公网目录映射。应用只通过授权接口读取 JPEG，不返回可共享的长期 URL。StorageProvider 抽象保留替换对象存储的边界；当前只实现私有本地卷，没有声称已验收 S3 或签名 URL。

StoredObject 清单独立于孩子和账号级联，记录 staging/live/purge_pending；Asset 删除后保留清理回执。Beat 每 60 秒发布清理，Worker 重试物理删除失败；超过 1 小时且无资产引用的暂存和规范路径孤儿文件可回收。清理只扫描自身存储根目录规范化的随机键，不跟随符号链接。删除单题/单图不会误删其他题仍引用的图片。备份中数据的留存与删除重放、DB+文件独立恢复尚待 Phase 7 验收。

## 开启 OCR 的前置条件

当前所有外发默认关闭、无启用模型/价格/预算种子；Compose Worker 的 dev/test 网络为 internal，不能直连供应商。即使填写环境变量，也不能把当前环境称为真实联调通过。

正式受控联调前，责任人须先完成授权脱敏样本、供应商图片能力与处理/留存条款、第三方告知、固定模型版本和有证据的费用上界审核。Admin 中 OCRModel 默认关闭；逐一配置 provider、精确 model_name、supports_vision、runtime_approved、notice/version、official_source、输入/输出上限。integration_verified 仅为记录标志，当前未宣称任何真实接入已验证。

平台模式还需 BudgetPolicy（正数全站累计/月/日/家庭日金额硬限额、家庭累计/日及用户日次数、固定预算时区）、有效 PriceVersion 和 Worker 专用平台凭证。金额使用币种微单位，价格为每百万 token 的微单位，不能填浮点“元”；输入 token 上界必须包括图像计费规则，有效窗口/证据不能用本轮合成测试价格替代。PriceVersion 新建后不可从 Admin 修改，创建新版本。

环境开关 OCR_OUTBOUND_ENABLED、PLATFORM_AI_ENABLED 仍需显式启用。API 仅配置平台凭证的 provider 元数据；PLATFORM_OCR_KEY_DEEPSEEK/KIMI 只注入 Worker，不给 API/Beat。BYOK 从加密库读取，绑定 actor/family/provider/credential_version；停用/替换/删除后排队任务不能使用旧版本。不得在前端环境变量、日志或队列消息中存密钥。BYOK 只记录用量/估价，不减平台预算或配额，也不代表供应商最终账单。

评测按 [OCR 基准说明](../quality/ocr-benchmark.md) 进行。没有真实凭证、条款、计费上界和足量真实样本时，继续使用手工录入，不强行开启。

## 事务预算、故障与恢复

创建任务时全局策略行锁串行化预算变更，在同一事务预占 4 个金额窗口和 3 个次数窗口，写账本与 Outbox。排队任务有最长 10 分钟的预占有效期，靠近日/月或价格切换窗口拒绝提交；Worker 发送前重检，HTTP 打开前再检查发送期限。边界不跨期挪用旧额度。

Outbox 可以重新发布排队任务；Worker 使用数据库状态和 lease 只允许一次领取。**只有确定未发出才全额释放金额**。已开始发送的网络超时、进程中断或缺用量响应，记录 unknown，保留金额预占并熔断平台模式，不自动重发。无效 OCR 文本但有有效用量时仍据实结算；失败请求返还业务次数，可能产生的费用不能归零。超出审核上界时记录真实用量/费用并熔断，不隐藏超额。

对账命令仅供有 `metering.change_budgetpolicy` 权限的活跃 staff；必须有供应商证据和原因：

```powershell
# 在目标环境的 manage.py 上执行，amount-micros 为核实后的整数金额
python manage.py reconcile_ocr --actor-id <operator-id> --job <job-id> --amount-micros <integer> --reason <evidence-reference>
```

只对平台 unknown 账本对账。对账后仍保持熔断，所有未决账本处理完后再由 Admin 审计修改恢复；管理表单从校验至保存持有同一策略行锁，未决费用存在时拒绝恢复。不可修改数据库来掩盖差额。取消已发送任务只丢弃结果，费用仍结算；授权撤回或资料删除后候选不得写回。

## 本地探针

`project.py test` 使用真实隔离 PG/Redis/Linux Worker，先跑 Django 测试，再跑 nonce 队列探针、queue_ocr_guard_probe。后者只允许 test 环境，创建自身合成夹具，生产者短暂模拟允许排队；独立 Worker 仍关闭外发，必须返回 OCR_DISABLED、sent_at=NULL、4/3 窗口预占归零并清理自身文件。它验证任务保护，**不验证供应商识别或计费质量**。
