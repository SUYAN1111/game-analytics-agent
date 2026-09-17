# 玩家行为分析助手

体验改版的阶段、细节、进度和下阶段提醒统一记录在 [四阶段体验改版记录](docs/UX_PHASES.md)。接续改版时先阅读该记录。

四阶段体验改版已完成：提问与结果层级、真实执行反馈、视觉与动效、结果旁的算法说明。[分析方法说明](docs/analysis-methods.md) 记录各方法的实际来源及展示边界；真实 DeepSeek 联调仍是单独的待验证工作。

本产品包含 Windows 本地分析核心、中文网页与 HTTP 接口。数据为固定模拟数据，服务仅监听本机。
网页默认使用本地规则识别常见分析意图和参数，经真实 DSH/MCP 工具及宿主核验返回结果。问候和明确无关请求在本地处理；缺少范围或规则无法理解的表达会请求补充，不偷换为示例问题。能力边界、澄清及部分完成协议见 [Agent 能力边界](docs/AGENT_SCOPE.md)。未请求真实付费模型 API，任意自然语言理解仍待真实模型联调；原实验结论与 Task13 两组 19/24 不变。

## 本地网页

前提：Windows x64、项目内 `.venv-core` / `.venv-dsh`（Python 3.14）、完整 `assets/`、Node >=22.12（本机验证 24.14.0）。前端锁定 React 19.1.1、TypeScript 5.9.2、Vite 7.1.7；Node 要求参照 [Vite 官方说明](https://vite.dev/guide/)。Python 环境尚未安装时先执行下面“安装与恢复”。

在项目根目录安装一次并构建：

```powershell
npm.cmd --prefix web ci
npm.cmd --prefix web run build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-web.ps1
```

离线启动（无需密钥）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-web.ps1
```

浏览器打开 **http://127.0.0.1:8765/**。脚本使用一个 worker、无自动重载；端口已占用时报告错误，不终止其他程序。开发界面可另开终端执行 `npm.cmd --prefix web run dev`，地址 http://127.0.0.1:5173/，通过代理调用 8765 接口。

五类入口为指标与版本比较、冻结预测、玩家分群、活动关联、口径与知识。点击示例只填入问题，点击发送后执行。图表与表格来自宿主核验后的公开结构化事实，完整核验原文及范围仍可展开。冻结预测仅支持 V6 历史 t0 快照公开汇总（对象数、缺失、覆盖率、平均概率）及知识说明，不预测新的任意对象。支持历史记录、追问、证据、复制回答及单次 Markdown 导出。所有数据均为模拟数据；引用核验不代表结论保证正确。

停止：启动窗口按 **Ctrl+C**；或另开 PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-web.ps1
```

执行中取消会回收本会话所属 Windows 进程树，并结束整个对话；排队取消保留对话。确认回收前显示正在取消。取消/超时可能留下未知费用预留，按原合同停止该模式共享预算，不能假定费用为零。重启后历史回答及证据可读，但旧对话只读；未完成任务标为中断，不自动重发。

网页元数据位于 `APP_STATE_DIR/web/{offline|live}/{period}/web.sqlite3`，预算位于同目录 `budget/`，默认周期 `default`。离线/live 完全隔离。重启同一周期不清零费用/预留/停止状态。需新周期时显式指定从未使用过的名称，例如 `-Period offline-demo-02`；保留旧记录，停止时使用相同 `-Mode` / `-Period`。不要通过删除账本解除停止。

真实模型入口（会使用 DeepSeek API；本次开发未调用）：

在项目根目录的 `.env` 中填写并保存一次密钥（没有此文件时可复制 `.env.example`）：

```dotenv
DEEPSEEK_API_KEY=在这里替换为你的真实密钥
```

以后在项目根目录运行以下命令，会自动读取 `.env`，不必每次输入密钥。若默认端口正在运行离线服务，先执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-web.ps1`，等待服务退出后启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-web.ps1 -Mode live
```

浏览器地址仍为 http://127.0.0.1:8765/ 。读取顺序为：现有进程环境变量 → 项目根目录 `.env` → 隐藏输入提示。修改 `.env` 后重启服务生效，无需重新构建或封版。不带 `-Mode live` 时仍为离线模式，不读取 `.env`。

`.env` 是本地明文文件，已被 Git 忽略，也不进入前端构建或发布校验清单；手动打包分享项目时也应排除它。不要把密钥贴到聊天、网页代码或命令参数中。启动脚本只读取文件中的 `DEEPSEEK_API_KEY`，不执行文件内容；密钥传给后台进程，退出时清除脚本设置的环境变量。其他配置仍通过原有环境变量设置。页面不能切换模式、端点、预算或工具。默认 H0，H1 仅保留 Python 启动配置 `--summary`。真实 API 浏览器、Linux、Vercel、公网部署均未验证。

开发验证命令（仅离线；浏览器脚本会执行取消并可能停止测试周期，请在独立周期服务上运行）：

```powershell
.\.venv-core\Scripts\python.exe -B -m product_core verify
.\.venv-core\Scripts\python.exe -B scripts\verify_web.py
.\.venv-core\Scripts\python.exe -B scripts\verify_lifecycle.py
node web\browser-check.mjs
```

浏览器验证使用本机 Chrome 独立临时配置，不依赖个人浏览器登录。HTTP 检查自行使用 8767 端口与独立离线周期。报告和真实截图写入 `state/task15/`。网页接口合同见 `docs/web-api.md`。

前端 `web/dist/` 和依赖不纳入源码提交；锁文件、源码及 `web/build-manifest.json` 纳入发布。启动校验构建字节与清单。开发修改后先构建，再显式执行 `.\.venv-core\Scripts\python.exe -B scripts\seal_release.py` 更新产品身份/源码清单/锚点，随后验证。此操作不在启动时自动执行，不改变冻结资产或其身份；清单与锚点排除自身，避免自引用。

## 文件与身份

源码包含十工具运行时、公开知识卡、来源文档、配置、发布校验及精简检查。
`product_release.json` 同时固定源码与全部必需资产的路径、大小、SHA-256；
`product_core/_release_anchor.py` 固定发布清单哈希。受信源码安装是信任起点，并非数字签名或抵抗攻击者改写整套源码的机制。
`provenance.json` 记录文件来源与提取修改；`upstream_provenance.json` 记录原正式登记验证链。
部分保留模块仍叫 task09/task12/task13，这是兼容命名，不会执行旧任务检查。

## 安装与恢复（PowerShell，Windows x64 / Python 3.14）

将 source ZIP 解压到独立目录，asset ZIP 解压到同一目录，得到 `assets/` 子目录。
若环境尚未安装，分别执行以下命令（首次环境安装通常需要联网下载锁定依赖）：

```powershell
Set-Location '<解压后的产品目录>'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m venv .venv-core
py -3.14 -m venv .venv-dsh
.\.venv-core\Scripts\python.exe -m pip install -r requirements-core.lock
.\.venv-dsh\Scripts\python.exe -m pip install -r requirements-dsh.lock
.\.venv-core\Scripts\python.exe -B -m product_core verify
$LASTEXITCODE
.\.venv-core\Scripts\python.exe -B -m product_core smoke
$LASTEXITCODE
```

DSH SDK/runtime 固定 0.1.5rc1，DSH 使用独立 Pydantic 2.12.5 环境。
有可信 wheel 缓存时，两条安装命令可加 `--no-index --find-links '<对应core或dsh缓存目录>'`。
本次恢复验证确实使用交付目录的独立依赖缓存，不使用原仓库环境或可编辑安装。
依赖缓存和虚拟环境均不在源码/资产 ZIP 中。Windows 专用 runtime wheel 无法替代 Linux 运行时。

## 资产与状态位置

网页的“管理数据源”支持选择 CSV、Excel `.xlsx` 或文件夹，在浏览器内预览表格、切换工作表、指定首行为列名、选择 UTF-8 / GB18030 编码，并手动对应字段。字段配置可以保存到当前浏览器或下载为 JSON；重新选择内容相同的文件可恢复配置。文件内容不上传、不持久保存到服务器。旧 `.xls` 需先另存为 `.xlsx`。

**自选文件目前处于预览与字段配置阶段，尚不驱动现有分析。** 页面持续显示实际使用的固定模拟数据源。任意新数据真正接入版本比较、预测、分组和关联，还需要数据校验、统计口径转换和模型兼容性适配；不能通过更换文件绕过现有资产校验。详见 [数据源说明](docs/data-source.md)。

默认只读资产根为 `<产品>/assets`，可用 `APP_ASSET_DIR` 指向完整解压的资产根。
默认可写状态根为 `<产品>/state`，可用 `APP_STATE_DIR` 指向独立目录。
路径不能彼此覆盖；没有资产或字节校验不符会报错，绝不回退读取实验仓库。
每次启动 Runtime 使用独立 UUID 目录，共享该 Runtime 内的一个预算协调器；每个 Session 有独立 UUID。
CLI 的独立 Runtime 预算不共享，不得用新建 Runtime 绕过业务全局限额；网页服务使用明确模式/周期绑定的持久账本与单进程锁。

运行产生的 SQL 索引、会话证据与预算写在 state 中，不复制冻结资产进每个会话。
`APP_DEBUG` 默认关闭；开启为 `1` 时两类 Python 协议细节日志及 DSH 调试流分别在 8 MiB 后停止追加，单条记录可能使文件略超阈值。
默认不额外写 24000 行候选审计副本，原始观测、采集依据、实际工具结果和回答引用仍可追溯。
必要工具证据、HTTP 计费记录、内部错误和未结算预留不自动删除。单轮最多 6 次模型请求、12 次工具调用、请求体 256 KiB；长期保留策略需由部署方制定。
取消/超时终止本会话所属 Windows Job；未知请求费用仍保留，并按原保守合同停止该 Runtime 后续请求。
完整关闭且无未结费用后，可以人工归档该 Runtime 整个状态目录；不能删除仍有未知费用的账本。
离线 `smoke` 会额外制作资产篡改测试副本，位于 `state/validation-*/tamper_assets`；仅验证用途，不属于产品必需资产。结果保存后可删除该测试副本。

## 调用接口与能力

`product_core.session.Runtime` 提供上下文管理器、`session()`、`turn()`、`cancel()`、`close()`。
同一 Session 拒绝并发 turn；不同 Session 独立进程、证据与上下文。真实执行路径为模型响应 → DSH 调度 → MCP 工具 → 宿主严格验证。
十工具：inspect_context、check_quality、query_metric、compare_results、predict_registered、read_model_card、get_evidence、search_knowledge、assign_segments、query_association_rules。
M03 保持取得资格后 72 小时未开始占比（Q5 / (Q4+Q5)），单位是用户×剧情。
冻结预测只做原 LR 模型的 t0 特征重放；全部七资产因原冻结状态契约共同校验而保留，绝不重新选择或训练。
分群仅用冻结 k=3 模型分配三份已冻结快照；关联仅对冻结六条规则与四份篮子复核计数，已移除拟合和挖掘入口。
知识检索仅搜公开卡片；来源文档仅用于来源核对，不作为全文发给模型。

CLI 实际模型演示入口是 `python -B -m product_core chat --live --budget-cny 5`，需要用户自行在进程环境设置密钥。本轮没有运行该命令，也不提供或保存真实密钥。
`/close` 关闭，Ctrl+C 取消并回收；返回的是宿主核验后的 `answer_markdown`。
`--summary` 对应原 H1 公开状态摘要，默认关闭（H0）。既有实验没有显示 H1 严格任务成功率提升。
模型 API 零自动重试；JSON 模式、每轮强制成功 inspect_context 后才 auto、数值/范围/单位绑定与知识引用核验保留。

## 验证及局限

查看 `VALIDATION_SUMMARY.md` 和交付目录 `EXTRACTION_REPORT.md`。
Python open 审计、实际第一方模块路径、锁定环境与静态闭包共同验证原库独立性；这不是操作系统级隔离，也不能覆盖所有原生库系统调用。
源码白名单包括必要的公开引用资料，有些原资料保留历史相对路径作为追溯说明，不构成运行读取依赖。
网页使用最小浏览器 Cookie 所有权绑定，不提供注册账号或公网多用户服务。SQLite schema 已版本化，尚无跨版本迁移需求。
Linux/Docker、真实模型回复、Vercel 与公网部署均未验证；跨平台运行需要另行移植和验收进程管理与预算通信。
