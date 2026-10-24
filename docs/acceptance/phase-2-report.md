# Phase 2 交付与验收报告

日期：2026-10-22，Asia/Shanghai。依据用户继续指令推进本地开发，授权解释见 [ADR-0006](../architecture/adr/0006-phase2-local-continuation.md)。

## 1. 结论

**PARTIAL**：当前阶段代码和本地功能验证完成，56 项后端测试、真实队列、H5/微信构建、浏览器建档与编辑通过。真实微信、真机与受信任 TLS 尚未验收，前端既有 braces 公告仍失败，公开发布 **NO GO**。没有自动进入 Phase 3。

## 2. 已实现内容

短期 Bearer、一次性刷新轮换/重用撤销、退出和 Redis 限流已实现。微信服务端 code 兑换边界已实现但未真实接入。显式本地测试适配器标记会话且无后台权限，默认关闭，部署配置拒绝开启。

家庭 owner、监护人/学生、指定孩子范围、限时单次邀请、成员撤销、最少孩子资料、监护授权/撤回、孩子删除和账号注销已实现。跨家庭和猜测 ID 拒绝，staff/superuser 也不能跨家庭访问业务 API。

凭证以 AES-256-GCM 加密，独立主密钥和版本、随机 nonce、认证归属、掩码、启停/替换/删除、旧版本失效和轮换命令已实现；无明文查询接口，Admin 不注册凭证/孩子/微信身份。原值要求 HTTPS，本地 HTTP 前后端均拒绝。

活动资格、自然月期限、家庭重复/互斥/容量、即时到期降级、资料保留、站内提醒和审计已实现。Admin 配置活动/基础限额、调整或撤销权益；授权操作员可用审计命令补发，仍遵守领取规则。没有扣款/支付/自动续费路径。

## 3. 文件与迁移

backend/apps/accounts、credentials、entitlements 为领域实现；tests/test_phase2.py 覆盖权限、加密、删除、权益和并发。新增四个领域迁移文件（accounts 两个，其余各一个）与三个 Admin 迁移；Phase 1 开发卷增量升级成功，独立测试 DB 从空库迁移成功。迁移总数 22。

frontend 提供家庭档案、AI 设置、免费权益三页和只在内存保存会话的客户端。Compose 新增单实例 Beat 与本地登录覆盖，脚本支持 `up --dev-login`。基础限额/主密钥显式初始化，无账号/活动种子。

最终应用镜像 ID：`sha256:b3d8eabdc3c37b978e32262c872e96c96f29b0eebdd171c7e9a523655ada1ca2`。底层 Python/PG/Redis 摘要保持 Phase 1 值。Git main 仍无提交/HEAD/远端，未推送。

## 4. 实际执行结果

| 检查 / 命令 | 结果与范围 |
| --- | --- |
| uv lock/sync，最终 lock --check | PASS，解析 66 项含虚拟项目，环境实际 65 项分发；新增 cryptography/whitenoise |
| Ruff check / format --check | PASS，64 个 Python 文件 |
| `project.py build` | PASS，非 root 镜像，构建时收集 Admin 静态资源，无运行时秘密 |
| `project.py migrate` / `check` | PASS，开发卷增量升级，check 0 issues，无待生成迁移 |
| `project.py test` | **56 通过、0 失败、0 跳过**，真隔离 PostgreSQL/Redis，测试 DB 销毁 |
| 真实队列探针 | PASS，任务 a306239d-dec5-4fc3-bc37-78c54a646ec7，非 eager |
| `up --dev-login` / health | PASS，5 服务运行；API/Worker/PG/Redis 健康，Beat 为运行状态；live/ready 均 200 |
| 正式 settings `check --deploy --fail-level WARNING` | PASS，.invalid 域名，无外部连接，仅 settings 静态检查 |
| 前端 type-check / format:check | PASS |
| build:h5 / build:mp-weixin | PASS；H5 28、微信 20 个 chunk 模块均不含 braces，不代表工具链漏洞关闭 |
| 浏览器 → API → DB → 页面 | PASS，测试登录、空态、建家庭/孩子、编辑、HTTP 凭证禁用、基础额度和无活动空态；浏览器 error 0 |
| 持久化与真实 Worker 删除 | PASS，PG 查询确认 UI 编辑落库；HTTP 删除后立即 404、Worker 完成；注销后 token 401、账号清理完成 |
| Admin 登录页 / CSS | PASS，HTTP 200，CSRF 表单和静态 CSS；未创建真实管理员或在浏览器操作运营活动 |
| pip-audit | PASS，退出 0，无已知漏洞 |
| npm audit | **FAIL**，18 high 受影响包、1 根公告 GHSA-vfj7-8cjw-p6xm；其他严重性 0，退出 1，无上游修复 |
| 源码/研发长片段/本地链接 | PASS，含原始两文件连续 100 字符扫描，无命中 |
| 本地秘密逐值检查 | PASS，非忽略源码、镜像配置/历史、API/Worker/Beat 最近日志均无生成秘密命中，仅输出计数 |
| 远端 CI / 微信真机 / 真 TLS / Provider | NOT TESTED 或 BLOCKED，没有伪报成功 |

首轮 52 项中 3 项错误字段请求误返回 500，定位为序列化器错误结构，修正后通过；新增权限、授权唯一性、便携更新和补发测试后共 56 项通过。微信端不支持 PATCH，页面改用同等权限验证的 POST 更新动作。

## 5. 权限与加密证据

覆盖匿名、本人、跨家庭、学生和后台高权限用户。学生仅可读取获授孩子，不能改档案/管凭证；移除成员撤销会话。授权撤回停止编辑，同用途只保留一个有效版本。其他拥有者凭证读/改/删/解密使用均拒绝，Admin 无凭证模型。HTTPS 检查、缺主密钥拒绝、替换/启停/删除失效、AAD 归属改动解密失败和主密钥轮换通过。

测试使用生成合成值，没有供应商请求；secure=True 只模拟 Django 安全请求属性。主密钥本机配置有效，但没有真实部署轮换、真实密钥浏览器提交或供应商可用性结论。

## 6. 权益和删除边界

覆盖月底/闰年/DST 歧义、窗口、新旧用户、暂停、重复、容量并发、跨家庭、到期即时限新增/保留旧资料、提醒失败回滚/重试且不改到期时间。没有扣费或隐式开通 AI 代码路径。

删除先撤销访问，数据库状态驱动幂等清理，Beat 恢复发布失败。保留最小回执/操作审计，正式留存周期和备份删除重放待后续流程。无私图，不能声称图片/导出级联删除验收。完整独立恢复仍 NOT TESTED。

## 7. 隔离与未完成范围

未复制原始 PRD/研发提示到页面、种子、夹具或 AI 模板。运行时 AI 模板清单为空，无题目/识别/统计演示种子。平台功能权益、平台 AI 额度和自有服务费用分别管理，本阶段只实现前者和凭证存储。

真实微信/TLS/真机、供应商连接、AI 偏好/调用、预算账本、OCR、私图、错题、题库和复习不在已完成声明中。部分权益功能名为后续预留，当前只验证扩展档案额度。braces 不 suppress，不以本地测试数量抵消发布阻断。

## 8. 复现与收尾

按 [本地手册](../development/local-development.md) 安装、初始化、构建、迁移、配置限额，再启动和测试。[实际 API](../api/phase-2-api.md) 和 [主密钥/删除运维](../operations/phase-2-operations.md) 说明操作与限制。

本机基础 3 个孩子档案、最多拥有 3 个家庭，无生效活动。专用 UI 验收账号/家庭/孩子已通过真实注销清理，未删除其他资料。截图位于忽略的 artifacts/phase2-family.png 和 phase2-benefits.png，表示清理前合成资料。收尾停止临时预览和本项目服务，保留数据卷。

## 9. 下一阶段条件

Phase 3 将实现私图/OCR/错题，首次外发前必须实现模式固定、预算/配额原子预留与缺配置拒绝，并准备授权脱敏图片和 OCR 凭证。微信/TLS 和依赖缺口继续列为阻断；不自动进入后续阶段或公开部署。
