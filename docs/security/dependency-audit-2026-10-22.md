# Phase 1 依赖审计与阻断

日期：2026-10-22。**结论：FAIL / 未关闭。** 当前没有批准的忽略项，CI 安全门禁保留非零退出。此报告只覆盖本阶段包依赖，不等同完整镜像/应用安全扫描。

Phase 2 复核：新增 cryptography 50.0.2、whitenoise 6.12.0，环境实际安装 65 项分发，pip-audit 退出 0、无已知漏洞。前端锁未变，重新 npm audit 仍为 18 high / 1 个根公告、退出 1。当前构建 H5 28 / 微信 20 个 chunk 模块均不含 braces；仍不能关闭工具链门禁。原始本轮 JSON 位于忽略的 artifacts/phase2-npm-audit.json；完整结果见 [Phase 2 报告](../acceptance/phase-2-report.md)。以下保留 Phase 1 修复历史。

## 实际结果

- Python：`uv run --project backend pip-audit` 审计 61 个包，已知漏洞 0，退出码 0。
- 前端首次正式 registry 审计发现多个公告；修复可用补丁后，最终 `npm audit` 为 high 18、moderate/low/critical 均 0，退出码 1。
- 最终 18 个受影响包都追溯到同一个根公告：**GHSA-vfj7-8cjw-p6xm / CVE-2026-93687**。不是 18 个独立根漏洞。braces <=3.0.3 的深层嵌套模式可导致递归栈耗尽；官方公告当前未列补丁版本。[GitHub 公告](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)

原始 JSON 在忽略目录 artifacts/pip-audit.json 和 artifacts/npm-audit-final.json，可在本地重跑；未将整个扫描结果或依赖源码塞入文档。

## 已做的修复

保留 DCloud 正式版 3.0.0-5020620260917001，不切 alpha。Vite 从模板 5.2.8 升为 6.4.5；本日官方支持说明仍将 6.4 列为安全回补分支。[Vite 支持策略](https://vite.dev/releases)

按具体公告固定 @babel/core、@intlify、adm-zip、jpeg-js、phin、postcss、selector-parser、source-map-js、ws、express、esbuild 的可用修复版本，清单以 frontend/package.json 的 overrides 和 package-lock.json 为准。未运行不受控的大版本自动修复。

Vue 运行时和编译器维持 DCloud 使用的 3.4.21；强行统一到 Vue 3.5 在真实浏览器触发 slot 更新错误，已撤回该路径并验证本页面状态变更。仅 server-renderer 通过显式覆盖升到 3.5.44 修复其公告；**SSR 不在兼容范围且配置中显式拒绝**。该覆盖不代表官方保证的通用组合，后续扩展组件必须重新做运行回归；应在官方工具链兼容更新后移除覆盖。

## 剩余风险和范围

braces 来自 glob/watch 等构建工具链；当前后端不安装此 npm 依赖，没有接收用户 glob 的 API。前端构建钩子记录 chunk 模块证据以判断 braces 是否进入输出，而不是凭体积或字符串猜测。即使客户端未包含它，开发/构建环境仍有风险，**不能因此把 audit 改成 PASS**。

本地开发仅绑定 127.0.0.1，当前不处理用户图片或不可信项目；禁止公开 Vite 服务或让外部用户控制构建 glob。这里是使用范围约束，不是漏洞修复或风险豁免。npm 还提示 phin 已停止维护，虽非当前根公告，后续应随上游工具链替换。

关闭条件：上游提供受支持修复或可靠维护的替代工具链，锁文件中不再包含受影响版本，复跑 npm ci/audit、类型检查、双端构建与浏览器状态路径。不得伪造包版本、改公告结果、禁用扫描或默认接受风险来进入下一阶段。
