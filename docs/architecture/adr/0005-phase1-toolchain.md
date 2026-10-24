# ADR-0005：Phase 1 实现与受限工具链

日期：2026-10-22。状态：实现已验证，依赖安全门禁仍失败；不是发布许可。

## 固定版本与结构

backend/uv.lock 使用官方 pypi.org，Python 3.12；实际 Linux 基础镜像运行 Python 3.12.15，本机隔离环境使用 3.12.10，不改变全局解释器。Django 5.2.18、DRF 3.18.3、Celery 5.6.3、psycopg 3.3.6、gunicorn 26.2.0。开发检查工具也锁定；生产镜像不安装 dev group。

PostgreSQL 18.6、Redis 8.2.10 和 Python 基础镜像均固定官方摘要，完整值见 compose.yaml/infra/Dockerfile。Redis 选已发布 GA 补丁，不使用 RC；镜像包含其许可证，生产部署仍需按使用方式核实许可证义务与当时支持期，不能把本地构建当作法律审批。

frontend/template-source.json 保存官方 vite-ts 模板 commit e5a5f0539416a0f012c919cc77949d140542a367，保留微信/H5 两个目标。正式编译器版本与 Vue runtime/compile 的约束保留；Vite 6.4.5、TS 5.9.3 及安全覆盖经过双端编译与具体浏览器路径验证。SSR 禁用，详情见 [依赖审计](../../security/dependency-audit-2026-10-22.md)。

## 本地与测试隔离

Compose 项目 tiyoujie-local。PG/Redis 只在 dev/test 内部网络，无宿主端口；API 另有 edge 网络并仅发布 127.0.0.1:18000。纯 internal 网络在本机 Docker Desktop 无有效宿主发布，实测后添加 edge；这不把数据库开放到宿主或公网。

数据库初始化为非超级用户：开发 tiyoujie_dev 无 CREATEDB，测试 tiyoujie_test 仅为独立测试实例允许 CREATEDB。迁移显式执行，启动不灌数据。test profile 强制服务主机、角色、DB、队列与运行标记；Django 测试不能指向 dev/prod。测试 nonce 任务只在 test 环境注册，无 HTTP 入队入口。

## 当前安全边界

无登录、家庭、孩子、凭证或领域表；无外部模型调用适配器，platform AI 与 dev login 固定关闭，环境变量不能擅自打开未实现能力。health 是唯一公开 API，其他默认权限为拒绝；后台页面尚未挂载。

日志只输出允许字段，抛弃消息参数和 traceback 内容；可观测性会牺牲异常堆栈，后续如增加安全的分类信息必须保持不泄漏请求/秘密。没有生产凭证，不做虚假的加密落库验证。

## 剩余决定

braces 无官方补丁时保留 audit 失败，不切 alpha、不自动迁移技术栈、不自行发布维护分叉。Phase 1 功能可审阅和本地运行，安全退出条件尚未满足；不得自动展开 Phase 2。
