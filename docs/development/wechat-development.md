# 微信小程序开发与本机工具

2026-10-24。本项目以微信小程序为用户端，uni-app 的 H5 用于辅助本地开发。用户提供的 AppID 已配置在 frontend/src/manifest.json 的 mp-weixin 中；AppID 是公开标识，AppSecret 只能位于后端的私密配置。

## 已验证与待验证

本机已安装并运行微信开发者工具，路径为 `C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat`。使用用户提供的 AppID 后，官方 CLI 对当前项目执行 open 返回成功；此前默认 touristappid 被拒绝，未继续使用游客身份或伪造 AppID。

项目已导入路径 `frontend/dist/build/mp-weixin`，不是 frontend/src。工具登录与应用登录不同：还需合法 HTTPS 后端、微信服务器域名配置，以及后端 WECHAT_APP_ID / WECHAT_APP_SECRET，才能执行真实 wx.login → 服务端 code2session。当前没有 AppSecret 或 HTTPS 后端，不能宣称真实微信登录/网络/相机已验收。

用户按 Esc 停止界面控制后，没有继续操作开发者工具界面，也未使用其他界面自动化绕过中断。模拟器页面交互、截图与真机验证仍 NOT TESTED；CLI 导入成功和编译通过不能替代这些证据。

## 仅预览本地界面

```powershell
py -3.12 scripts/wechat.py build --ui-only
# 需要自行打开时执行；本轮导入已完成，没有上传或发布代码
py -3.12 scripts/wechat.py open --ui-only
```

此模式不伪造接口，API 地址为空，小程序首页显示“界面预览”，不发送登录/题目请求。HTTPS 和合法域名检查保持开启。build 生成 tiyoujie-build.json 记录公开构建配置；open 校验 AppID、构建地址和域名检查一致，发现旧配置则拒绝。

## 接通后端后构建

在微信平台为该 AppID 配置合法接口域名，后端完成真实 TLS、反向代理可信配置和 AppSecret 私密注入。不要在聊天、前端 env 或仓库提交 AppSecret/API Key。

```powershell
py -3.12 scripts/wechat.py build --api-base https://你的合法接口域名
py -3.12 scripts/wechat.py open --api-base https://你的合法接口域名
```

API 地址必须是无路径/查询/片段/内嵌凭证的 HTTPS origin。工具默认取 manifest 中的 AppID，也支持 `--appid` 或 WECHAT_APP_ID；`--cli` 可指定已安装的官方 CLI。缺配置时不改成 HTTP，也不关闭证书或域名校验。

前端还提供 `npm run dev:mp-weixin` 用于增量编译；其输出在 frontend/dist/dev/mp-weixin，真实联网时同样须显式配置公开 VITE_API_BASE_URL 和合法域名。默认 `build:mp-weixin` 仍可独立编译，辅助脚本提供配置校验和导入流程。

脚本只有 build/open，不执行 preview/upload，不生成云端预览码，也不发布体验版或正式版。SDK CLI 网页本轮抓取失败，参数依据本机官方 `--help` 和实际 open 结果核对。开发者工具打印的 punycode 弃用提示来自安装的 CLI，与应用业务测试结果分开记录。
