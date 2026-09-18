# 云端适配本地验收（2026-09-18）

本轮实现 Vercel 请求内执行入口、Linux 进程组与 Unix socket 适配、PostgreSQL 持久化及共享预算、访问码和浏览器归属隔离、资产构建流程与手动 Linux CI。保留原 DSH/MCP 工具与宿主证据核验，不将后台替换成静态答案。

## 已实际执行

- Windows / Python 3.14，云端适配器连接本机 PGlite 0.5.8 + pglite-socket 0.2.11。它通过 PostgreSQL 协议执行 SQL，但不能替代真实 PostgreSQL 的完整并发或事务语义验收。
- `scripts/check_cloud_store.py`：提交幂等、跨浏览器隔离、单次 claim、持久用量、取消后拒绝预留、失联任务不重跑、未知费用保护暂停、真实删除且保留预算，通过。
- `scripts/check_cloud_runtime.py`：本地模型桩 + 真实 DSH/MCP，五项成功。版本比较 7 项证据，知识说明 2 项，冻结预测 5 项，分群 10 项，关联 3 项。新建 Service 实例仍可读取回答；删除后无法读取。报告为 `state/cloud-runtime-results.json`，`paid_calls=0`。
- 真实 Chrome 桌面浏览器经过访问码登录、自由输入比较问题，前端触发请求内分析并展示结果；刷新后恢复数据库结果与证据，无脚本错误。截图 `state/cloud-test/cloud-answer.png`，记录 `state/cloud-test/browser-result.json`。
- 真实 Chrome 手机布局 390×844：访问码、同源检查、参数拒绝、本地问候、不同浏览器隔离、删除后 404，无横向溢出。截图 `state/cloud-test/mobile.png`。
- 新增 `scripts/check_cloud_http.py` 持续回归首次登录后并行请求保持同一个 owner，访问与参数校验、问候及真实删除。已通过。此项发现并修复登录前后并行 API 首次设定 cookie 的竞态。
- 数据库禁用自动预编译，并在事务内设置 search_path、超时，以适配连接池。修改后 HTTP 数据库路径再次通过。
- 前端 TypeScript / Vite 构建、分析方法绑定、用量展示、能力范围、执行状态以及发布完整性检查通过。资产打包为 60 项原登记文件，没有改变冻结资产身份。

## 尚未执行

- Linux / Python 3.14 的实际 DSH 子进程、依赖包和进程组生命周期。当前电脑无可用 Linux/Docker 环境。
- 真实 PostgreSQL 16、Neon 连接池、多实例竞争的完整实测。
- Vercel 的构建、路由、原生依赖执行、300 秒截止、2 GB 内存限制、冷启动、部署包体、断线行为和免费额度消耗。
- 适配后的云端真实 DeepSeek 自由表达与追问。此前 Windows 本地真实 DeepSeek 结果见原报告，本轮无新增付费调用。

手动 GitHub 工作流 `.github/workflows/cloud-acceptance.yml` 会运行 Linux + PostgreSQL 16 + 本地模型桩的 HTTP 和五能力验收。Vercel 上仍须按 [部署指南](VERCEL_DEPLOYMENT.md) 做实际测试。不能将本轮通过结论表述为“已在 Vercel 上线”或“保证全免费”。
