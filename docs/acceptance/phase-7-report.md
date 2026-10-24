# Phase 7 开发与验收报告

日期：2026-10-24。目录：D:/cursor-project/tiyoujie。**本轮补齐备份恢复演练、生产编排与发布/回滚手册，并完成全量测试与依赖复核。真实主机、TLS、微信真机与真实供应商仍未验收，公开发布 NO GO。**

## 1. 本轮交付

| 交付 | 位置 | 说明 |
| --- | --- | --- |
| 备份入口 | `scripts/backup.py` | PostgreSQL 自定义格式 dump + 私有存储归档 + 清单/SHA-256，输出到 `backups/`（已忽略） |
| 恢复演练 | `artifacts/phase7_restore_drill.py` | 通过真实 API 造数据 → 备份 → 独立容器恢复 → 哈希比对 → 真实注销清理 |
| 生产编排 | `infra/deploy/compose.prod.yaml` | 固定镜像 digest、无数据库宿主端口、Redis 密码、资源与日志限制、nginx 前置 |
| 反向代理 | `infra/deploy/nginx.conf`、`proxy_params_tiyoujie.conf` | TLS 1.2/1.3、HSTS、限速、上传上限、健康检查 |
| 部署/回滚手册 | [运维手册](../operations/phase-7-deployment.md) | 构建、秘密、迁移、启动、备份、恢复、回滚、轮换、故障 |
| 环境模板 | `infra/deploy/env.prod.example` | 全空值；真实值不进入仓库 |

## 2. 恢复演练结果（真实执行）

来源：`artifacts/phase7-restore-report.json`

```
status passed
backup_seconds 0.61              database_restore_seconds 0.33
media_files_backed_up 1          media_files_restored 1
media_hash_match true
migrations 38                    tables 55
guard_triggers 18                checks 82
fixture_problem_restored 1       fixture_asset_restored 1
fixture_cleanup succeeded
```

演练步骤：

1. 通过真实 HTTP 接口创建测试身份、家庭、孩子、错题并上传真实 PNG（8×8）。
2. `scripts/backup.py` 生成数据库 dump 与包含该图片的媒体归档。
3. 启动一次性 PostgreSQL 容器（与生产相同镜像 digest），`pg_restore` 恢复。
4. 把媒体归档解压到一次性卷，逐文件重算 SHA-256，与备份清单完全一致。
5. 在恢复库中确认：迁移数、表数、触发器数、约束数，以及测试题目与图片记录均存在。
6. 通过真实注销接口删除测试账号，Worker 完成清理后旧令牌失效。

**已覆盖**：数据库结构与数据、私有文件内容、触发器/约束随备份恢复、备份与恢复耗时（该数据集下 RPO≈0、RTO<1 秒，不代表生产数据量）。
**未覆盖**：异机/加密传输、对象存储、跨版本恢复、生产规模数据量、恢复后的账本与权益重算校验。

## 3. 静态配置验证

| 检查 | 结果 |
| --- | --- |
| 生产编排合并 `docker compose config --quiet` | PASS（合成占位值，不启动容器、不连接数据库） |
| `manage.py check --deploy`（prod，`.invalid` 主机） | PASS，0 issues |
| 弱 secret 拒绝 | PASS：`ImproperlyConfigured: Missing or invalid configuration: DJANGO_SECRET_KEY` |
| 生产启用 dev login 拒绝 | PASS：`Development login is forbidden in deployment` |
| 生产 CSRF origin 非 HTTPS 拒绝 | PASS：`Deployment CSRF origins must use HTTPS` |
| 全量测试 | 193 通过、0 失败、0 跳过（隔离 PG + 真实 Redis/Worker） |
| npm audit / pip-audit | 0 已知漏洞（npm 全等级 0；pip-audit 66 个依赖无命中） |
| 前端 format:check / type-check / 双端构建 | PASS（最终复跑：format 0、type-check 0、H5 0、mp-weixin 0） |

未真实执行：TLS 握手、证书续期、nginx 启动、跨机备份、数据库主从、容器在目标主机的资源表现。

## 4. 门禁更新

| ID | 变化 |
| --- | --- |
| G11 独立恢复 | NOT TESTED → **本地 PASS（范围有限）**：单机隔离容器、同版本恢复、含媒体哈希与业务行校验；异机与生产规模仍 BLOCKED |
| G14 部署/回滚/轮换手册 | NOT TESTED → **PARTIAL**：脚本、编排与手册就绪，未在目标环境演练 |
| G10 全量测试与构建 | PASS（本轮复跑） |
| G12 微信/TLS/真机 | 仍 BLOCKED |
| G07/G08/G09 真实质量与题库许可 | 仍 BLOCKED |

## 5. 仍需责任人提供

1. 目标服务器（Linux、Docker）、域名与 TLS 证书。
2. 微信 AppSecret 与小程序后台合法域名配置权限。
3. 隐私政策、监护人告知文本与保留期确认。
4. OCR/AI 供应商合同、价格与授权样本（若上线自动识别/分析）。
5. 真实题库授权与审核人（若上线同类题推荐）。

在以上缺项关闭前，发布结论保持 NO GO；可上线的范围仅限人工错题、题单、复习、导出及已有的家庭/权限能力。
