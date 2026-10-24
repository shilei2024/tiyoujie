# ADR-0002：模块化单体与版本候选

日期：2026-10-22。状态：技术路线接受，版本为候选，依赖解析/安全扫描/运行兼容性未验收。

Phase 1 补充：以下表格保留 Phase 0 候选快照；实际已锁定/实测版本与兼容限制见 [ADR-0005](0005-phase1-toolchain.md)，依赖安全门禁未通过，不能把候选表或编译成功当作安全结论。

采用 Django + DRF 模块化单体、独立 Linux Celery Worker、PostgreSQL、Redis、私有存储；微信端使用 uni-app Vue 3 TypeScript，管理端先 Django Admin。不引入微服务、云函数、独立后台 SPA 或强制向量库。

## 核查与候选

| 组件 | 本日官方 / 发布源核查 | 建议基线与理由 |
| --- | --- | --- |
| Python | 本机另有 3.12.10；默认 3.9.13 | 3.12 系列，Phase 1 选当日最新安全补丁，隔离环境，不修改 Anaconda |
| Django | 下载页列最新 6.1.2、5.2 LTS 最新 5.2.18；5.2 延长支持至 2028-04 | 5.2.18 LTS 候选，减少无关大版本迁移 |
| DRF | 官方发布说明与 PyPI 为 3.18.3，声明支持 Django 5.2 与 Python 3.12 | 3.18.3 候选，包含近期安全修复 |
| Celery | 官方 stable 文档与 PyPI 为 5.6.3；不支持 Windows | 5.6.3 候选，Worker/Beat 在 Linux 容器运行 |
| PostgreSQL | 官方表列 18.6，支持至 2030-11；本机 CLI 相同 | 专用 18.6 容器候选；pgvector 暂不启用 |
| Redis | 已核查官方版本管理与 8.10.2 release；支持期/许可证仍需部署前复核 | Phase 1 复核受支持 GA 系列，锁补丁/digest 并实测 Celery，禁用 RC/latest 浮动标签 |
| psycopg | PyPI 3.3.6，Python >=3.10 | 3.3.6 候选，需与 Django/PG 容器集成测试 |
| cryptography | PyPI 50.0.2 | Phase 2 引入；先审计依赖与平台 wheel，不自行实现加密 |
| Pillow / SymPy | PyPI 13.0.0 / 1.14.0 | 分别 Phase 3 / 5 引入，当阶段复核并锁定 |
| uni-app | 官方 vite-ts 模板的 DCloud 包统一为 3.0.0-5020620260917001，npm 精确版本可查询 | 以正式模板快照为候选，不直接安装 vue3 dist-tag 的 alpha |
| Vue / TypeScript / Vite | npm 最新 Vue 3.5.44、TS 7.0.2；模板仍声明 Vue ^3.4.21、TS ^4.9.4、Vite 5.2.8 | 不把各包最新版任意拼接；模板只是起点，旧 Vite/TS 的安全支持与升级兼容必须在 Phase 1 验证 |
| Node / 包管理 | 本机 22.23.2 / npm 11.12.1；DCloud 文档要求现代 Node | 先用本机 Node 22，运行双目标构建后再锁；不用全局升级 |

候选不是锁文件。Phase 1 必须生成 `uv.lock`、`package-lock.json`，记录模板 commit SHA、镜像 digest、依赖漏洞检查和例外，不以这张表代替安装解析。发现模板依赖有未修复风险时停止该构建门禁、评估官方升级路径，不自动换成 alpha 或换技术栈。不能把本机 Python 3.12.10 当作仍是最新安全补丁。

## 一手来源

- [Django 下载与支持期](https://www.djangoproject.com/download/)、[Python 兼容表](https://docs.djangoproject.com/en/5.2/faq/install/)。
- [DRF 发布说明](https://www.django-rest-framework.org/community/release-notes/)、[DRF 发布元数据](https://pypi.org/pypi/djangorestframework/json)。
- [Celery 支持与操作系统限制](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)、[Celery 发布元数据](https://pypi.org/pypi/celery/json)。文档版本要求段存在 5.5 旧文字，5.6 兼容性应结合当版元数据及实测。
- [PostgreSQL 版本策略](https://www.postgresql.org/support/versioning/)。
- [Redis 版本管理](https://redis.io/docs/latest/operate/oss_and_stack/install/version-mgmt/)、[Redis 8.10.2](https://github.com/redis/redis/releases/tag/8.10.2)。
- [Django 5.2.18](https://pypi.org/pypi/Django/5.2.18/json)、[psycopg](https://pypi.org/pypi/psycopg/json)、[cryptography](https://pypi.org/pypi/cryptography/json)、[Pillow](https://pypi.org/pypi/Pillow/json)、[SymPy](https://pypi.org/pypi/sympy/json)。
- [DCloud CLI](https://uniapp.dcloud.net.cn/quickstart-cli.html)、[官方 vite-ts 模板](https://github.com/dcloudio/uni-preset-vue/tree/vite-ts)、[模板 package.json](https://raw.githubusercontent.com/dcloudio/uni-preset-vue/vite-ts/package.json)、[uni-app 精确版本](https://www.npmjs.com/package/@dcloudio/uni-app/v/3.0.0-5020620260917001)。

## 微信限制与缺口

按 request/uploadFile/downloadFile 分别核实生产合法域名、HTTPS、隐私授权、订阅消息权限和代码包体积。官方网络文档本次抓取失败，不能据旧教程写死平台当前包大小、并发或上传上限。Phase 1 校验编译产物；Phase 2/3 在开发者工具和真机核对当前官方规则及最低基础库。暂不实现前端直连供应商、公开图片 URL 或依赖浏览器 DOM 的公式组件。

[微信网络文档入口](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html) 未成功读取，列为待核验来源，不能算已确认。H5 成功也不能代替微信编译和真机验收。
