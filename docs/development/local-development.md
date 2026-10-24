# 本地安装、启动、检查和停止

适用范围：Phase 2 本地开发；不是生产部署脚本。所有命令在项目根目录执行，除非另行指定。PowerShell 使用 `py -3.12`，Linux/macOS 可替换为 `python3`（3.12）。

## 1. 安装隔离依赖

需要 Git、Docker Linux daemon / Compose、Python 3.12、uv 0.13.1、Node 22 / npm。默认 Anaconda 不用于项目。首次获取代码后：

```powershell
uv sync --project backend --frozen
py -3.12 scripts/bootstrap.py
cd frontend
npm ci
cd ..
```

bootstrap 仅创建忽略的 `.env` 随机本地秘密；已有文件不会覆盖，输出不含值。空 `.env.example` 不能直接作为有效配置。Windows 的 chmod 不能代替生产 ACL/秘密管理，本地配置不能复用到部署。

依赖审计仍有未关闭的上游公告，见 [审计记录](../security/dependency-audit-2026-10-22.md)。不要运行 `npm audit fix --force`，它可能将 DCloud 包回退到不兼容的旧主版本。全局包管理配置保持不变，项目 npm 使用官方 registry。

## 2. 构建、显式迁移与启动

```powershell
py -3.12 scripts/project.py preflight
py -3.12 scripts/project.py build
py -3.12 scripts/project.py migrate
py -3.12 scripts/project.py check
py -3.12 scripts/project.py up
```

`migrate` 显式应用 Django 基础表、Admin 和 accounts/credentials/entitlements 迁移，不创建账号或演示数据。启动 API 不自动迁移；缺必要领域迁移时 ready 返回 503。首次 DB 容器启动只创建独立数据库/非超级用户角色。

家庭/孩子基础限额不内置为生效种子，首次使用显式配置。本次本机已配置每家庭基础 3 个孩子档案、每用户最多拥有 3 个家庭；它不是会员赠送或活动。新环境可按需要调整参数：

```powershell
docker compose -p tiyoujie-local run --rm --no-deps api python manage.py configure_limits --basic-children 3 --max-families 3 --reason "Local development setup"
py -3.12 scripts/project.py up --dev-login
```

`--dev-login` 仅适用于 up，加载本地覆盖文件，页面明确显示测试会话。普通 up 将恢复默认关闭；部署 settings 直接拒绝测试登录。不要把本地身份当作微信账号。登录身份、会话、邀请码和密钥均不输出到操作日志。

`up` 启动 API、Worker 与 Beat，等待具备健康检查的服务就绪，并从宿主机验证 live/ready；Beat 每分钟调度权益和删除恢复扫描。API 仅本地 `127.0.0.1:18000`，PG/Redis 无宿主端口。开发/测试分离，API 额外挂 edge 网络，Worker/Beat/DB 在内部网络。不可复制启动多个 Beat。

健康检查：

```powershell
py -3.12 scripts/project.py health
```

## 3. 前端与编译

另一个终端在 frontend 目录运行：

```powershell
npm run dev:h5
```

打开 [http://127.0.0.1:15173/](http://127.0.0.1:15173/)，测试登录后自行创建家庭和档案。H5 代理 `/api` 至 18000；不要暴露开发服务器。页面仅在内存保留会话，刷新需重新登录；密钥提交在本地 HTTP 禁用，凭证输入提交后/离页清空。无题目或统计演示种子。

```powershell
npm run type-check
npm run format:check
npm run build:h5
npm run build:mp-weixin
```

产物位于 frontend/dist/build/h5 与 frontend/dist/build/mp-weixin。微信 AppID 留空，不伪造正式配置；正式预览需自行在合法环境配置真实 AppID、HTTPS API 与合法域名。`frontend/.env.local` 可设 `VITE_API_BASE_URL=https://已配置的后端域名`，此处只能放公开地址，绝不能放秘密。H5 静态部署也需同源 `/api` 反向代理或构建时配置合法 HTTPS 地址。

客户端只做 H5/微信编译；SSR 显式禁用。依赖锁含安全覆盖，兼容范围仅为已验证路径，不代表所有 uni-app 插件兼容。构建同时输出 artifacts/frontend-modules-*.json 用于核对工具依赖是否进入客户端。

## 4. 自动检查

Phase 4 更新：使用 mp-weixin 作为主客户端；AppID 已配置，微信 CLI build/open 及 HTTPS 联调步骤见 [微信小程序开发](wechat-development.md)。本地界面预览不连接后端、不关闭域名检查。分析/提示/人工修订与运营预警见 [Phase 4 运维](../operations/phase-4-operations.md)。当前 project.py test 为 135 项后端测试及三个真实队列探针；另执行 `py -3.12 -m unittest discover -s tests -v`，3 项微信配置检查通过。以下 Phase 3 的数量与说明保留为历史。

```powershell
uv run --project backend ruff check backend scripts
uv run --project backend ruff format --check backend scripts
py -3.12 scripts/check_repository.py
uv run --project backend pre-commit run --files backend/manage.py scripts/project.py
py -3.12 scripts/project.py test
uv run --project backend pip-audit
```

在 frontend 运行 `npm audit --audit-level=low`：2026-10-24 审计通过；此前 braces 公告于 10 月 23 日撤回。CI 继续使用完整失败门禁，没有 suppress/ignore/continue-on-error，未来审计非零必须排查。

test 命令在 PostgreSQL tmpfs 上创建 test_tiyoujie_isolated，执行当前全量测试（Phase 7 为 193 项）并销毁测试 DB，再由真实 Linux Worker 跑 nonce 和 OCR 禁止外发探针；finally 停止三个测试服务。OCR 探针在独立基础测试 DB 迁移并创建自身合成资料，结束时清理，全程不调用供应商。直接在 dev 执行 manage.py test 会拒绝。API 测试中的 secure=True 只验证 HTTPS 检查逻辑，不等于真实 TLS 验收。

错题入口位于家庭页“我的错题本”。先选择孩子，可手动录题或选图片，在本机预览裁剪、确认去除身份信息后上传。H5 使用本地原生 Canvas，微信产物使用 uni Canvas；微信实际权限/相机/裁剪效果须真机验收。未配置模型/预算时仍可手工管理，OCR 默认关闭。私图和预算配置见 [Phase 3 运维](../operations/phase-3-operations.md)，数据评估见 [OCR 基准](../quality/ocr-benchmark.md)。

可选 `scripts/check_repository.py --requirements-dir <两份原始需求所在目录>` 额外检查去空白后的连续 100 字符匹配；只输出命中文件名，不复制来源内容。该启发式扫描不能替代人工评审。

## 5. 停止与恢复

前端终端 Ctrl+C 停止开发服务器；根目录执行：

```powershell
py -3.12 scripts/project.py down
```

只停止/移除 tiyoujie-local 项目的容器和网络；不使用 `-v`、不清理开发数据库/私有文件卷、不影响其他项目。重新启动先确认配置未更换，再按 migrate/up 操作。已有卷的数据库密码不会随 .env 自动修改，不要删除卷“解决”密码不一致。

当前包含领域表和用户自行创建的业务资料。升级前备份数据库并保管独立加密主密钥；不要用反向迁移删除领域表。回退代码/镜像前审查兼容性，不能套用 Phase 1 的空业务假设。DB+私有文件备份恢复仍须 Phase 7 演练。管理后台、主密钥和删除操作详见 [Phase 2 运维](../operations/phase-2-operations.md)。

## 6. 本地备份与恢复演练

```bash
py -3.12 scripts/backup.py                      # 输出 backups/tiyoujie-<UTC 时间>/
py -3.12 artifacts/phase7_restore_drill.py      # 备份 + 一次性容器/卷恢复 + 哈希校验 + 清理
```

要求本机 Docker 与开发服务正在运行；脚本只访问 `tiyoujie-local` 项目的 `postgres-1` 容器与 `private_dev` 卷，不打印密码。演练会临时启动 `tiyoujie-restore-drill` 容器与卷，结束后自动删除，并在 `artifacts/phase7-restore-report.json` 记录备份/恢复耗时、表数、触发器数、媒体哈希是否一致。备份目录已在 `.gitignore` 中，不能提交。

生产主机的等价命令与保留策略见 [Phase 7 部署手册](../operations/phase-7-deployment.md)。
