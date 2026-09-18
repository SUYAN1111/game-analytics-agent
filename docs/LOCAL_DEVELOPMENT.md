# 本地开发指南

本指南面向需要安装、恢复、开发和验证本项目的使用者。项目概览和常规启动见 [README](../README.md)，云端操作见 [Vercel 部署指南](VERCEL_DEPLOYMENT.md)。以下命令均在仓库根目录的 PowerShell 中执行。

## 环境与依赖

本地已验证环境为 Windows x64、Python 3.14、Node.js 24.14.0；Node.js 最低要求为 22.12。两个 Python 环境用途不同，不要合并：

| 环境 | 锁文件 | 用途 |
| --- | --- | --- |
| `.venv-core` | `requirements-core.lock` | HTTP 服务、分析代码、MCP 工具与核验 |
| `.venv-dsh` | `requirements-dsh.lock` | DeepSeek Harness SDK/runtime 0.1.5rc1，独立 Pydantic 2.12.5 |

首次安装：

```powershell
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m venv .venv-core
py -3.14 -m venv .venv-dsh
.\.venv-core\Scripts\python.exe -m pip install -r requirements-core.lock
.\.venv-dsh\Scripts\python.exe -m pip install -r requirements-dsh.lock
npm.cmd --prefix web ci
npm.cmd --prefix web run build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-web.ps1
```

安装依赖需要联网。已有可信安装包缓存时，可为 pip 添加 `--no-index --find-links '<缓存目录>'`。Windows 的虚拟环境和 runtime 安装包不能直接复制到 Linux 使用；云端通过 `scripts/build_vercel.py` 安装独立的 `_core_vendor` 和 `_dsh_vendor`。

根目录 `requirements.txt` 是 Vercel 的基础依赖入口，本地安装应使用上面两个完整锁文件。

## 分析资产

`assets/` 不提交 Git。它包含发布清单登记的 60 项模拟数据、模型、规则和运行资产，必须与当前 `product_release.json` 匹配。只下载源码无法完成分析。

本次资产包名为 `asset143f285f40e8357711e76382ff.zip`。维护者已在本地生成此包，但本次文档更新时尚未确认可公开下载的 Release 附件地址。新使用者需要先获取匹配的资产包；不能用任意 CSV 替代它。

由 `scripts/pack_cloud_assets.py` 生成的 ZIP 内部直接包含 `runtime/`、`models/` 等目录，**应解压到项目的 `assets/` 中**。解压后至少可看到：

```text
game-analytics-agent/
├── product_release.json
├── README.md
└── assets/
    ├── runtime/host.json
    ├── models/
    ├── segmentation/
    └── association/
```

例如，已将对应 ZIP 放入项目根目录时执行：

```powershell
Expand-Archive -LiteralPath .\asset143f285f40e8357711e76382ff.zip -DestinationPath .\assets
.\.venv-core\Scripts\python.exe -B -m product_core verify
```

如果拿到的旧交付包本身已经包含顶层 `assets/`，应解压到项目根目录，避免产生 `assets/assets/`。不要覆盖来源不明的现有资产；缺失或哈希不符时，重新获取对应发布的完整文件。

维护者在已有完整资产的机器上重新打包：

```powershell
.\.venv-core\Scripts\python.exe -B scripts\pack_cloud_assets.py
```

输出位于 `state/cloud-assets/`，同时生成记录文件大小和 SHA-256 的 `bundle-info.json`。该命令只打包清单登记的资产，不包含 `.env`、源码或运行历史。云端下载会逐项检查目录、大小和哈希。

## 密钥与启动

正常启动默认使用真实 DeepSeek，自动读取根目录 `.env`。读取优先级为现有进程环境变量 → `.env` → 隐藏输入提示；脚本只读取 `DEEPSEEK_API_KEY`，不执行文件内容。

```dotenv
DEEPSEEK_API_KEY=your_deepseek_api_key
```

`.env` 是本地明文配置，已被 Git 忽略；手动打包分享时同样需要排除。修改密钥后重启服务即可，不需要构建或重新封版。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-web.ps1
```

浏览器地址：**[http://127.0.0.1:8765/](http://127.0.0.1:8765/)**。

启动前会检查两个环境与锁定依赖，并做一次不携带密钥、不调用模型的 DeepSeek HTTPS 连通性检查。连通性检查和打开首页不消耗模型 token；发送分析问题可能产生费用。HTTP 连通不代表真实分析一定能完成。

| 启动参数 | 默认值 | 作用 |
| --- | --- | --- |
| `-Mode` | `live` | `live` 调用 DeepSeek；`offline` 使用本地模型桩 |
| `-Period` | `live-main` | 绑定持久预算和历史记录周期 |
| `-Port` | `8765` | 本机监听端口 |
| `-Budget` | `4.9` | 周期限额，人民币；已有账本需与初始化值一致 |

同一周期重启不会重置用量、预留或停止状态。不要通过换周期、删账本或重复新建 Runtime 来绕过预算。当前默认值沿用已有本地配置；历史网络问题和旧账本处理记录保留在 [体验记录](UX_PHASES.md)。

停止正常服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-web.ps1
```

它按模式和周期请求优雅停止。若启动时改变了 `-Mode` 或 `-Period`，停止时也要传相同参数。端口已占用时，启动脚本会报错，不会直接结束其他程序。

### 离线开发与浏览器回归

在一个终端运行独立测试服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-web.ps1 -Mode offline -Period offline-browser -Port 8766
```

在另一个终端运行浏览器检查，需已安装 Chrome：

```powershell
$env:WEB_TEST_URL = 'http://127.0.0.1:8766'
$env:WEB_TEST_OUTPUT = 'state/offline-browser'
node web\browser-check.mjs
```

此脚本执行真实工具并覆盖多种成功与取消场景，可能需要数分钟。离线模式不读取 `.env`，不会调用付费模型；它仍可能触发测试账本的保护暂停。测试结束后停止对应服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-web.ps1 -Mode offline -Period offline-browser
```

不要对日常 live 服务运行带失败注入或取消的回归脚本。

### 前端热更新

后台运行时可另开终端启动 Vite：

```powershell
npm.cmd --prefix web run dev
```

地址为 **[http://127.0.0.1:5173/](http://127.0.0.1:5173/)**，默认代理到 8765 后台。代理目标若是 live，发送分析仍会调用真实模型。需要离线前后端联调时，先按同模式/周期停止原 8765 服务，再显式在 8765 启动 offline 后台。

## 状态、历史与费用

| 数据 | 本地位置 |
| --- | --- |
| 只读分析资产 | 默认 `<项目>/assets`，可用 `APP_ASSET_DIR` 指定完整资产根 |
| 可写运行状态 | 默认 `<项目>/state`，可用 `APP_STATE_DIR` 指定 |
| 网页对话与证据 | `APP_STATE_DIR/web/{mode}/{period}/web.sqlite3` |
| 共享预算及每次启动的运行记录 | 同周期目录的 `budget/` 下 |

源码、资产与状态根必须按路径规则分离。`APP_ASSET_DIR` 只是定位匹配资产，不允许任意替换分析数据。

本地服务使用 SQLite、一个 worker 和单进程锁。重启后已完成记录可读，旧对话只读，未完成任务标为中断，不自动重发。历史归属由浏览器 Cookie 绑定；没有账号登录或跨设备历史同步。

取消运行中的任务会结束所属对话，并回收受控进程树。只有确认回收后才发布取消终态。费用未知时保留预留并暂停后续调用，不将缺失回执解释为免费。删除对话会删除关联的网页历史与证据，不删除费用账本；内部审计记录另有保留要求。

`APP_DEBUG` 默认关闭；开启后协议调试流有 8 MiB 的追加上限，单条记录可能略超阈值。审计与计费文件不宜直接作为公开附件，浏览器状态文件可能含所有者 Cookie。README 截图只复制了已经检查的界面图片。

## 验证与发布校验

以下命令无需付费模型：

```powershell
.\.venv-core\Scripts\python.exe -B -m product_core verify
.\.venv-core\Scripts\python.exe -B scripts\check_scope_routing.py
.\.venv-core\Scripts\python.exe -B scripts\check_public_usage.py
.\.venv-core\Scripts\python.exe -B scripts\check_execution_store.py
node web\test-analysis-methods.mjs
```

完整 HTTP 和生命周期验证会自行管理独立离线服务及测试周期：

```powershell
.\.venv-core\Scripts\python.exe -B scripts\verify_web.py
.\.venv-core\Scripts\python.exe -B scripts\verify_lifecycle.py
```

运行时需完整资产和独立依赖；默认 HTTP 测试使用 8767，先确保端口空闲。工具级离线验证还可执行 `python -B -m product_core smoke`（使用 `.venv-core` 中的 Python），会在 `state/` 生成篡改测试用资产副本。

### 修改后的发布步骤

`product_release.json` 固定源码、文档与全部必需资产的文件路径、大小和 SHA-256；`product_core/_release_anchor.py` 固定清单哈希。`web/build-manifest.json` 固定前端产物。此机制用于检查可信安装的一致性，不是数字签名，也不是操作系统级沙箱。

完成有意的开发修改后执行：

```powershell
# 前端源码或静态文件改变时先构建
npm.cmd --prefix web run build

# 显式更新发布身份、构建清单与源码锚点
.\.venv-core\Scripts\python.exe -B scripts\seal_release.py
.\.venv-core\Scripts\python.exe -B -m product_core verify
```

仅修改 Markdown 时无需重新构建前端，但文档也属于源码清单，需要执行后两条命令，并一并提交更新后的发布清单和锚点。封版要求已有可校验的 `web/dist/`；它不重新计算资产哈希、不训练或修改冻结模型。

保留 `.gitattributes` 的字节策略。Windows CRLF 检查可用 `git -c core.whitespace=cr-at-eol diff --check`；不要自动改换行符后忽略完整性失败。缺失或来源不明的文件应先恢复，不应通过重新封版使它“通过”。

### 验证报告如何阅读

根目录 `VALIDATION_SUMMARY.md` 是早期独立提取验证记录，其中的 NOT_RUN 仅代表当时状态。历史报告提到的 `working_validation.json`、`EXTRACTION_REPORT.md` 等交付文件不一定包含在当前 Git 仓库中。当前总体状态以 [README 的验证状态](../README.md#验证状态) 及对应日期报告为准。

Linux CI 需要本地 PostgreSQL 测试服务和匹配资产，已由手动工作流提供；不要将云端测试脚本指向生产数据库。Windows/PGlite 的检查通过不能替代 Linux/PostgreSQL/Vercel 实机验收。

## Python 与 CLI 入口

`product_core.session.Runtime` 提供 `session()`、`turn()`、`cancel()` 与 `close()`，同一会话拒绝并发 turn。正常网页使用服务周期共享预算；直接创建独立 Runtime 不会自动合并不同 Runtime 的预算。

CLI 的真实模型入口为：

```powershell
.\.venv-core\Scripts\python.exe -B -m product_core chat --live --budget-cny 5
```

CLI 要求调用进程环境已有 `DEEPSEEK_API_KEY`，不会自动读取 `.env`，实际调用会计费。日常使用应优先运行网页启动脚本。输入 `/close` 关闭，Ctrl+C 取消；`--summary` 是历史 H1 对照配置，默认 H0，现有实验没有证明 H1 提高严格任务成功率。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 `.venv-core` / `.venv-dsh` | 按完整锁文件分别安装两个 Python 3.14 x64 环境 |
| `product_integrity` 或资产缺失 | 确认匹配资产包和目录，运行 `product_core verify` |
| 网页构建缺失或字节变化 | 执行前端构建；开发修改需显式封版，普通安装不应重封 |
| `ERR_CONNECTION_REFUSED` | 确认启动终端无报错，地址为 `http://127.0.0.1:8765/`，不要带说明文字 |
| DeepSeek HTTPS 检查失败 | 检查外网与代理；在允许联网的终端启动，尚未发起模型调用 |
| 分析暂停 | 查看错误、已记录用量和未结算预留；核对后再人工恢复，不删除账本 |
| 自选表格后结果没有变化 | 目前只有预览和字段映射，分析仍使用固定模拟资产 |
