# 仓库与环境盘点

检查日期：2026-10-22，用户时区 Asia/Shanghai。所有结果来自实际本地只读检查。

## 工作区基线

| 项目 | 检查结果 |
| --- | --- |
| 工作目录 | `D:\cursor-project\tiyoujie` |
| 初始文件 | `Get-ChildItem -Force` 返回空目录 |
| Git | `git status --short` 返回 not a git repository；退出码 128 |
| 分支、HEAD、未提交变更 | 不适用：未初始化 Git，不声称工作区 clean |
| 上级规则 | `D:\AGENTS.md`、`D:\cursor-project\AGENTS.md`、工作目录 `AGENTS.md` 均不存在 |
| 已有依赖、业务、测试、部署配置 | 无 |
| 修改边界 | 仅创建 README 和 docs 下的研发设计文档；原始需求文件未改动 |

需求来源位于用户给定的 Downloads 文件夹。该文件夹名称实际包含 `%E6...` 等字面编码，直接使用原始路径可读；URL 解码后的路径不存在。已完整读取两份文件，不将其存档或加载到运行时。

来源快照 SHA-256（`Get-FileHash -Algorithm SHA256`，便于后续判断需求版本是否变化）：

| 文件 | SHA-256 |
| --- | --- |
| Codex_分阶段开发总提示词.md | `8DBDC6115E2215AE7B8DA323D7D9554AE48E518A842CB83B7FFCDA5457972A5A` |
| PRD_数学错题管理系统.md | `10AF1ED6F62EF68E5EA44B18D0BA16BEA9D6DF088BA66842DA7F9B0DF6BB5223` |

## 实测工具

| 工具 / 资源 | 结果 | 对后续开发的影响 |
| --- | --- | --- |
| OS | Windows 11 专业版，10.0.26200，64 位 | Worker 在 Linux 容器运行 |
| PowerShell | Core 7.6.5 | 使用原生 PowerShell 文件操作 |
| 物理内存 | 47.79 GiB | 仅为开发机资源，不代表云服务器 |
| D 盘可用空间 | 133,283,684,352 bytes，约 124.13 GiB | 镜像和测试数据仍需限制体积 |
| Git | 2.55.0.windows.3 | 可用于 Phase 1 初始化，不自动提交 |
| 默认 Python | 3.9.13，来自 Anaconda | 不在此环境装项目依赖 |
| 独立 Python | `py -3.12 --version` = 3.12.10 | 可建立隔离虚拟环境；容器使用受支持的最新 3.12 补丁 |
| uv | 0.13.1 | Phase 1 管理独立环境和锁文件 |
| Node / npm | 22.23.2 / 11.12.1 | 前端候选工具链，编译尚未验证 |
| Docker Engine / Compose | 29.8.0 / v5.5.1 | 守护进程可访问，非仅安装 CLI |
| Docker 后端 | linux x86_64，32 CPU，内存 25,083,740,160 bytes | 未拉取镜像或启动容器 |
| PostgreSQL CLI | psql 18.6 | 未连接数据库；不使用宿主机现有数据库作为测试库 |
| Redis 服务程序 | PATH 未发现 redis-server | 计划使用专用 Linux 容器 |

复现命令：

```powershell
Get-ChildItem -Force
git status --short
git --version
python --version
py --list
py -3.12 --version
uv --version
node --version
npm --version
docker version --format '{{.Server.Version}}'
docker compose version
docker info --format '{{.OSType}} {{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}}'
psql --version
```

## 外部环境状态

没有提供目标服务器配置、登录授权、域名、TLS 证书、对象存储、微信 AppID/Secret、真实 API 凭证、合法题库或授权脱敏 OCR 图片。未搜索私人凭证目录，也没有连接任何生产数据库。服务器 OS/CPU/内存/磁盘、网络出口、备案、备份空间与实际费用均未知。

Docker 可访问只证明后续可以尝试容器构建；不证明项目构建、健康检查、真实 OCR 或部署已成功。
