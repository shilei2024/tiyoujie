# Phase 6 API：题单、作答、复习与导出

日期：2026-10-24。所有接口位于 `/api/v1/`，需要 Bearer 访问令牌；权限与对象归属沿用家庭/孩子授权模型。响应中不会出现其他家庭的数据。

## 1. 题单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `worksheets/?child_id=&page=` | 有孩子访问权 | 分页 20，按创建时间倒序 |
| POST | `worksheets/` | 监护人 | `{child_id, title}`；需 profile 监护授权 |
| GET | `worksheets/{id}/` | 有孩子访问权 | 含题目快照；监护人可见答案，学生仅在有作答记录后可见 |
| DELETE | `worksheets/{id}/` | 监护人 | `{confirm: true}`；同时撤销未过期导出票据 |
| POST | `worksheets/{id}/items/` | 监护人 | `{origin, problem_id \| bank_item_id \| variant_id}` |
| GET | `worksheets/{id}/items/{item_id}/` | 有孩子访问权 | 含该题作答记录；答案按上表规则隐藏 |
| DELETE | `worksheets/{id}/items/{item_id}/` | 监护人 | 移除后自动重排题号 |
| POST | `worksheets/{id}/items/{item_id}/attempts/` | 有孩子访问权 | `{answer, self_grade, duration_seconds?}` |

### 题项快照与来源可见性

- `origin=problem`：保存当前已确认题干的文本与答案快照；之后修改或删除错题不会更新题单内容，删除错题会级联移除题单项。
- `origin=bank`：只保存题库题目 ID、修订号与文本快照。来源被撤回、过期或修订变化时，接口返回 `source_available=false` 并隐藏文本，作答返回 `409 ITEM_UNAVAILABLE`。
- `origin=variant`：绑定生成时的题干版本；题干已变更时拒绝加入（`409 REVISION_CONFLICT`）。
- 若同一孩子已有同一错题，返回 `409 ITEM_DUPLICATE`；单份题单最多 30 题，单孩子最多 200 份。

## 2. 作答与评分

`POST worksheets/{sheet}/items/{item}/attempts/`

```json
{ "answer": "计算过程或结果", "self_grade": "correct|wrong|unsure", "duration_seconds": 45 }
```

- 题项带结构化算式且填写了答案时，服务端用 `math_verifier` 自动比对（`graded_by=auto`），不采信与核验结果冲突的自评。
- 无结构化算式或核验不支持时，按 `self_grade` 记录（`graded_by=self`）；`unsure` 的 `is_correct` 为 `null`，不计入正确率分子或分母以外的推断。
- 每题最多 20 次作答；作答记录不可修改。
- 错题来源的作答会推进间隔复习；题库题与变式题只记录练习，不进入错题复习计划。

## 3. 间隔复习

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `reviews/queue/?child_id=` | 今日到期 + 无复习计划的新错题，最多 20 条 |
| POST | `problems/{id}/review/` | `{grade: correct\|wrong\|unsure}` |

算法（确定性，无模型调用）：

- 间隔阶梯：1、3、7、14、30、60、120 天。
- 答对：前进一级；连续答对 ≥ 4 且间隔 ≥ 30 天记为 `mastered`。
- 不确定：退一级，连续答对次数不变。
- 答错：回到 1 天，`streak=0`，`lapses+1`。
- 日期按 `PRACTICE_TIME_ZONE`（默认 `Asia/Shanghai`）的日历日计算，与数据库 UTC 存储分离。

响应含 `due_on`、`stage`、`interval_days`、`streak`、`lapses`；每次判定写入不可修改的 `ReviewEvent`。

## 4. 趋势

`GET children/{id}/trends/?weeks=1..26`（默认 8）

- 按本地周一分桶：`problems_added`、`attempts`、`correct`、`wrong`、`unsure`。
- `sample`：总作答数与 `min_required=10`；不足时 `sufficient=false`，前端不得显示正确率结论。
- `knowledge_points`：每个知识点作答次数；不足 5 次时 `accuracy=null`、`insufficient_sample=true`。
- 统计只覆盖未删除错题与未删除题单，最多读取 5000 条作答。

## 5. 导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `exports/` | `{kind: worksheet\|summary, child_id, worksheet_id?}`，监护人 |
| GET | `exports/{nonce}/?file=html\|csv` | 需同一账号 Bearer；返回 HTML 或 CSV 文件；题单默认 HTML |

- 票据有效期 10 分钟，可撤销；题单删除、孩子档案删除、票据过期均返回 `410 EXPORT_EXPIRED`。
- 题单导出为自包含 HTML：CSP `default-src 'none'`，无外链字体/图片/脚本，`Cache-Control: no-store`，所有动态文本转义；授权题库题目附带来源、许可与署名。
- 学习概览导出为 CSV：UTF-8 BOM，`= + - @` 开头的单元格前置 `'` 防止公式注入。
- 不生成服务器端永久文件，导出内容在请求时重新渲染，因此不存在“删除后仍可下载旧文件”的残留。

## 6. 错误码

| 代码 | HTTP | 场景 |
| --- | --- | --- |
| `CONFIRMED_TEXT_REQUIRED` | 400 | 错题未确认题干 |
| `CHILD_REQUIRED` | 400 | 缺少或非法 `child_id` |
| `SCOPE_MISMATCH` | 400 | 题单/孩子不一致 |
| `RIGHTS_NOT_APPROVED` | 409 | 题库授权不可用 |
| `ITEM_DUPLICATE` / `ITEM_LIMIT` / `WORKSHEET_LIMIT` | 409/403 | 重复题、容量上限 |
| `ITEM_UNAVAILABLE` | 409 | 来源变化或删除 |
| `ATTEMPT_LIMIT` | 409 | 单题作答超过 20 次 |
| `REVISION_CONFLICT` | 409 | 题干版本过期 |
| `EXPORT_EXPIRED` | 410 | 票据过期/撤销/对象删除 |
| `RATE_LIMITED` | 429 | 频率限制触发 |
