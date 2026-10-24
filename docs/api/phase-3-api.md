# Phase 3 已实现接口

2026-10-24。路径前缀 `/api/v1/`，沿用内存 Bearer 会话、20 条分页和安全错误封装。匿名 401、其他家庭或未获授孩子 404、学生只读。家庭 guardian 才能变更，staff 身份不绕过领域权限。未知输入字段拒绝。

| 路径 | 方法 | 行为 |
| --- | --- | --- |
| problems/?family_id= | GET / POST | 列表；创建时传 child_id 和可选分类字段 |
| problems/{id}/ | GET / PATCH / DELETE | 查看、按 expected_revision 更新分类；删除传 confirm=true，202 表示文件待清理 |
| problems/{id}/update/ | POST | 微信端可使用的分类更新动作，与 PATCH 权限一致 |
| problems/{id}/text/ | POST / PATCH | text、answer、confirmed=true、expected_revision，可选同题 parent_id；追加人工确认版本 |
| problems/{id}/text-versions/ | GET | 降序分页历史；不存在编辑旧版本接口 |
| problems/{id}/assets/ | POST multipart | 唯一 file；不接受其他字段和多文件 |
| problems/{id}/asset-links/ | POST | asset_id、expected_revision；只允许同孩子图片关联 |
| problems/{id}/assets/{asset_id}/remove/ | POST | expected_revision；解除本题引用，末次引用消失后安排物理清理 |
| assets/{id}/content/ | GET | 每次校验身份后返回 JPEG 字节，no-store/nosniff；无公开媒体 URL |
| assets/{id}/transforms/ | POST | problem_id、expected_revision、regions、split；矩形 crop + 顺时针 0/90/180/270°，最多 8 框 |
| ocr/models/ | GET | 已启用且获准的视觉模型及第三方告知；outbound_enabled 单独返回 |
| problems/{id}/ocr-jobs/ | GET / POST | 最近 20 项任务状态；POST 创建异步识别 |
| tasks/{id}/ | GET | 领域权限内状态、错误码和费用状态，无凭证/原始供应商响应 |
| tasks/{id}/cancel/ | POST | 取消排队任务或标记运行任务取消；已发送仍可能产生费用 |
| usage/summary/?family_id= | GET | 平台剩余次数/状态，与用户自己的 BYOK 用量分别返回 |

列表支持 child_id、grade（1..12）、chapter、error_type、date_from、date_to、knowledge_point、q（题干版本/章节）、page。分类字段为 source、chapter、knowledge_points（最多 10 个）、error_type、mistake_date。OCR 候选不会自动成为 current_text；必须由监护人载入、校对、勾选并保存新版本。

图片实际仅接受单帧 JPEG/PNG/WebP，8 MiB、1200 万像素、最大边 8192；客户端下采样不能替代服务端验证。所有入库图重新编码为 JPEG、移除元数据、使用随机对象键。默认家庭 100 MiB、每题 8 张、每家庭 1000 道，可在部署配置中收紧。分题事务失败不留下部分领域记录，暂存文件由清理任务回收。

OCR POST 必须携带 `Idempotency-Key`（16–64 位字母数字/下划线/短横线）及 asset_id、model_id、billing_mode、expected_revision、notice_version、cost_confirmed=true。模式只能为 platform_trial 或 byok，后者必须显式选择 credential_id。相同 actor+key+负载返回原任务，负载不同 409；不会因供应商超时而自动换模式或重发请求。

外发前，Worker 再验证所有权、孩子访问范围、图片引用和哈希、监护/第三方授权、模型/告知版本、凭证版本以及预算窗口。缺配置拒绝，无真实模型种子。本地 OCR 模型目录为空；手工录题和图片管理可使用。
