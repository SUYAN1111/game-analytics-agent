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

- 修复后的 Linux DSH/MCP 五能力和进程组生命周期验收。首次 Linux 运行的通过项与失败项见下节；当前电脑无可用 Linux/Docker 环境。
- 真实 PostgreSQL 16 的持久化完整回归、Neon 连接池和多实例竞争实测；首次 Linux HTTP 检查已连接真实 PostgreSQL 16 通过。
- Vercel 的构建、路由、原生依赖执行、300 秒截止、2 GB 内存限制、冷启动、部署包体、断线行为和免费额度消耗。
- 适配后的云端真实 DeepSeek 自由表达与追问。此前 Windows 本地真实 DeepSeek 结果见原报告，本轮无新增付费调用。

手动 GitHub 工作流 `.github/workflows/cloud-acceptance.yml` 会运行 Linux + PostgreSQL 16 + 本地模型桩的 HTTP 和五能力验收。Vercel 上仍须按 [部署指南](VERCEL_DEPLOYMENT.md) 做实际测试。不能将本轮通过结论表述为“已在 Vercel 上线”或“保证全免费”。

## 首次 Linux 失败排查与本地修复

[GitHub Actions 35299773816](https://github.com/SUYAN1111/game-analytics-agent/actions/runs/35299773816)，提交 `e4a68d4`，Ubuntu 24.04 / Python 3.14.7 / PostgreSQL 16：

- 依赖安装、公开资产下载与完整性检查、前端构建、数据库初始化、HTTP 身份隔离与删除检查通过。
- 五能力检查的第一个比较任务返回 `failed`、证据数 0。原实现清理了内部日志，不能仅凭此运行确认最内层异常；Node.js Action 弃用提示属于警告。
- 本地复现：清除 `PYTHONPATH` 后，`python -m` 不会自动执行当前目录的 `sitecustomize.py`。原来的 Linux 桥接、MCP、预测子进程依赖这条隐式加载路径，而所需依赖只装在 `_core_vendor`。
- 改为固定模块白名单的 `python -S -m cloud_api.core_bootstrap`，显式加载核心依赖。DSH 继续使用独立入口及 Pydantic 2.12.5，核心使用 2.13.4。删除失效的 site hook，传递必要的 Linux 动态库路径，不继承模型或数据库凭据。
- 审查固定 MCP 2.2.0 代码发现，默认 stdio 传输在 Linux 使用 `start_new_session=True`。新增仅在独立桥接进程内生效的版本绑定适配，保留 MCP 协议与传输，令 MCP 留在宿主进程组，并在启动时验证归属。服务进程退出与宿主最终清理分工明确；实际 Linux 回收仍待 CI 验证。
- 离线检查失败时也写出报告，在删除临时运行目录前收集有限的启动日志，脱敏后仅交给离线测试。网页公开错误不增加内部细节。新增依赖入口预检和故障注入检查。

修复后的 Windows 本地回归：HTTP 检查通过；故障注入验证失败报告、脱敏、临时目录清理及公开 DTO 隔离通过；五类真实 DSH/MCP 分别得到 7、2、5、10、3 项证据，全部成功，新 Service 恢复与删除通过；新增引导入口的依赖隔离检查及 MCP 适配的归属拒绝、退出、还原逻辑检查通过。依赖探针为适配 Windows 的 pywin32 补充了原生模块搜索目录，不能当作 Linux 运行结果。没有调用付费 API。

本机详细记录位于忽略目录 `state/cloud-failure/regression/`。需要手动提交并推送修复后，从 **Run workflow → main** 新建一次运行；旧提交的 **Re-run jobs** 不会读取本次修复。资产附件和 `ASSET_BUNDLE_URL` 继续复用。
