# 2026-10-24 依赖审计复核

Phase 4 复核：未新增外部依赖；再次运行 npm/pip 审计均退出 0，已知漏洞为 0。新产物为 artifacts/phase4-npm-audit.json、phase4-pip-audit.json。微信开发者工具 CLI 的 punycode 弃用提示单独记录，不当作应用安全扫描失败或忽略新的安全公告。

本轮 `npm audit --json` 退出 0：info/low/moderate/high/critical 均 0；`pip-audit --format json` 退出 0：无已知漏洞。npm 仍使用 registry.npmjs.org；没有 ignore、suppress、continue-on-error 或虚构版本。新增 Pillow 13.0.0 已纳入 uv 锁文件及 Python 审计。审计产物保存在忽略的 artifacts/phase3-npm-audit.json、phase3-pip-audit.json。

Phase 1/2 的 18 个 high 受影响包来自同一个 braces 根公告。该公告已于 2026-10-23 撤回，官方说明不构成实际可利用漏洞：[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)。因此本轮依赖门禁按当前数据更新为 PASS；不是升级到了不存在的补丁。历史报告保留当时 FAIL 结果，不能覆盖旧证据。

Vue 运行时仍固定 3.4.21，避免 uni-app 插槽兼容问题；SSR 禁用，编译器与运行时同版本覆盖维持既有配置。H5 和微信构建通过不代替后续依赖审计。CI 每次仍执行完整安全扫描，新公告出现时照常阻断。

本结论仅为本轮依赖已知漏洞检查。真实微信、TLS、OCR 供应商、隐私条款、授权样本与独立恢复等门禁仍需关闭，不能据此公开发布。
