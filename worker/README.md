# Worker

Worker 复用 backend 镜像与 config.celery，不复制业务实现。开发服务没有业务任务；test profile 才注册 infrastructure.test_probe。探针只能由测试 CLI 发起，无 HTTP 入队端点。

Celery 在 Linux 容器中运行，使用 JSON、专用队列、短期测试结果；不发送 OCR/AI 请求。未来付费任务需经过事务预算与 Outbox 后另阶段实现。
