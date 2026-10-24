# 验证入口

`python scripts/project.py test` 使用专用 postgres-test、redis-test、worker-test，在独立网络与 tmpfs DB 中运行 Django 测试与真实队列探针。结束时停止这三个测试服务，不停止开发 API，不删除开发卷。

后端测试位于 backend/tests；覆盖环境拒绝、测试目标保护、日志字段白名单、真实 PG/Redis readiness 和故障 503。故障注入只替代失败分支，正常路径实际连接 PG/Redis。队列探针在单独 Linux Worker 上执行，不使用 Celery eager。

当前无 OCR 样本、真实 Provider 或微信真机验收；H5/微信编译通过不代表这些能力已验证。
