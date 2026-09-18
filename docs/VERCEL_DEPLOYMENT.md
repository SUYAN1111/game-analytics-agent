# 手动部署到 Vercel

仓库已实现云端代码、数据库持久化、构建配置和 Linux 自动验收。**Neon 已初始化，Vercel 已部署。完整公网日志确认 `close_failed` 的起因是临时磁盘写满。已将 SQLite 索引从约 342 MiB 缩小到 132 MiB，并串行解压数据；本地全部玩家数据核对、五类真实工具和重复统计通过。仍须推送本次更新、运行新增的 512 MiB 磁盘限制 Linux 验收，并验证公网分析。** 具体通过项和限制见 [云端排查记录](CLOUD_VALIDATION_2026-09-18.md)。

网页和分析后台都放在 Vercel；Neon PostgreSQL 只负责保存对话、证据和费用账本。不需要自己购买、维护一台服务器，也不需要 Docker 或 MySQL。DeepSeek 仍使用真实 API，分析数据仍是项目现有的固定模拟数据。

## 1. 将源码提交并推送到 GitHub

由你手动操作。项目根目录是包含 `vercel.json`、`api/`、`cloud_api/`、`web/` 的这一层。

提交本次新增和修改的源码、文档、配置、锁文件、`product_release.json`、`product_core/_release_anchor.py`、`web/build-manifest.json`，以及 `.github/workflows/cloud-acceptance.yml`。不要只提交 `web/`。

现有 `.gitignore` 已排除 `.env`、`assets/`、`state/`、虚拟环境、依赖、构建产物及数据库文件。提交前在编辑器的“暂存的更改”里确认没有密钥和这些目录。不要修改 `.gitattributes` 的 `* -text`：发布校验固定文件字节，自动改换行符会导致云端校验失败。

本次磁盘占用修复建议提交说明：`fix: reduce cloud temporary disk usage`。已部署的项目只需更新代码，继续使用原有五项环境变量、数据库和资产附件，不需要重新建项目、上传附件或运行初始化 SQL。`runtime-assets.zip` 是构建时生成的文件，已被 `.gitignore` 排除，不提交到 Git。

## 2. 上传模拟数据资产包

资产包已经在本机生成：

```text
state/cloud-assets/asset143f285f40e8357711e76382ff.zip
```

大小 **25,612,256 字节，约 24.4 MiB**。SHA-256：

```text
455b9f3f40ef0b08957c716d34c5a62b2846b402466491e0a76f94211cb294b2
```

打开 GitHub 仓库 → **Releases → Draft a new release**，创建一个标签，例如 `cloud-assets-v1`，在附件区上传这个 ZIP，发布 Release。复制该附件的下载链接，通常形如：

```text
https://github.com/你的用户名/仓库名/releases/download/cloud-assets-v1/asset143f285f40e8357711e76382ff.zip
```

用未登录的浏览器确认这个链接能直接下载。若源码仓库是私有的，可以单独建一个公开的模拟资产仓库来放附件。这里公开的是项目模拟资产，今后的真实业务数据不能沿用公开上传方式。

不要使用 GitHub 自动生成的 `Source code (zip)`，不要把 GitHub token 放进链接。构建程序只接收清单登记的 60 个文件，并逐项检查大小、路径和哈希。资产保持不变时，以后的代码更新可以继续使用同一个附件。

需要重新生成时，在项目根目录运行：

```powershell
.\.venv-core\Scripts\python.exe -B scripts\pack_cloud_assets.py
```

## 3. 先运行 GitHub 的 Linux 验收

进入源码仓库 **Settings → Secrets and variables → Actions → Variables → New repository variable**：

| 名称 | 值 |
| --- | --- |
| `ASSET_BUNDLE_URL` | 上一步复制的公开 ZIP 下载链接 |

然后进入 **Actions → Cloud Linux acceptance (no paid API) → Run workflow**，选择本次代码所在分支。

新版工作流会在真正限制为 **512 MiB** 的临时文件系统中，解压完整数据包，执行五类分析并重复一次剧情统计，验证连续请求的空间占用及清理。它使用本地模型桩，不调用付费 API。检查产物中的 `cloud-runtime-results.json` 应为 `PASS`，包含磁盘容量、峰值占用和六次执行结果。

这个流程在 Linux / Python 3.14 上安装隔离依赖、下载并校验资产、构建网页，在临时 PostgreSQL 16 上验证访问隔离，以及版本比较、口径说明、预测、分群、玩法关联五类真实工具链。模型使用本地测试桩，**不需要 DeepSeek 密钥，也不调用付费模型**。Actions 自身使用你的 GitHub 账户额度；若账户提示额度或账单要求，先查看提示，不需要为此直接升级套餐。

全部步骤变绿才进入下一步。若变红，保留失败步骤的日志用于定位；不要跳过校验或在云端重新封版来强行通过。结果 JSON 可在此次运行的 Artifacts 中下载。这里不会自动操作你的 Vercel 项目。

修复代码后，先手动提交并推送，再从 **Run workflow → main** 新建运行。不要在旧失败页面点 **Re-run jobs**，它仍使用原提交。资产不变时不需要重复上传附件或修改 `ASSET_BUNDLE_URL`。新增入口预检报告为 `cloud-bootstrap-results.json`；分析失败也会生成含脱敏诊断的 `cloud-runtime-results.json`。

## 4. 创建免费数据库并初始化

在 [Neon](https://neon.com/) 注册，选择 **Free** 计划创建 PostgreSQL 项目。选择与后续 Vercel 函数接近的区域。

在 Neon 的连接设置中选择连接池（Pooled connection），复制完整连接字符串，后面应保留 SSL 参数，例如 `sslmode=require`。这个字符串包含数据库密码，只粘贴到 Vercel 后台环境变量中。

进入 Neon 的 **SQL Editor**，将仓库 [cloud_api/schema.sql](../cloud_api/schema.sql) 全部内容复制进去并执行。再单独执行以下初始化语句：

```sql
INSERT INTO agent_cloud.budgets(id, payload)
VALUES (1, '{"limit_cny":1,"max_attempts":336,"attempts":[],"tools":[],"closed_sessions":[],"stopped":false}')
ON CONFLICT (id) DO NOTHING;
```

这里将新云端账本初始分析限额设为 **1 元人民币**，用于控制首次测试范围；它不是充值，也不是供应商提供的账户账单上限。运行在本机或其他程序中的 API 消耗不计入这份云端账本。重复执行不会清空已有用量或解除暂停。不要靠删除账本或新建数据库来绕过预算暂停。

连接池适配使用事务内设置和事务锁，不依赖跨事务保持连接状态，见 [Neon 连接池说明](https://neon.com/docs/connect/connection-pooling)。数据库账号应专用于这个应用。

## 5. 导入 Vercel 项目

打开 [Vercel 新建项目](https://vercel.com/new)，通过 GitHub 导入刚推送的源码仓库。选择适合个人用途的 Hobby 计划，先确认页面显示的套餐和额度。GitHub 关联后，后续推送可以触发部署，见 [Vercel Git 集成](https://vercel.com/docs/git)。

| 设置 | 本项目的值 |
| --- | --- |
| Root Directory | 仓库根目录 `./`，不要选 `web` |
| Framework Preset | `Other` |
| Install Command | `npm ci --prefix web` |
| Build Command | `uv run --no-project --python 3.14 --with pip==25.3 python scripts/build_vercel.py` |
| Output Directory | `web/dist` |
| Node.js Version | `24.x` |
| Python | 函数运行时由 `.python-version` 指定 `3.14`；构建命令另用 `uv --python 3.14` 明确选择版本 |
| Fluid compute | `vercel.json` 已设置 `"fluid": true`，无需寻找控制台开关 |
| Large Functions | `vercel.json` 的 `build.env` 已设置 `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` |
| 函数最长时间 | `vercel.json` 已设置 300 秒 |

这些命令已写入 `vercel.json`，控制台不要覆盖成单独的 Vite 前端构建。当前 Vercel Python 支持 ASGI 和流式响应；Hobby Fluid 函数最长 300 秒。参见 [Python 运行时](https://vercel.com/docs/functions/runtimes/python) 和 [函数限制](https://vercel.com/docs/functions/limitations)。

不要将 Build Command 简化为 `python scripts/build_vercel.py`：`Other` 预设下，这可能调用构建镜像的默认 Python，而不是 `.python-version` 所要求的函数运行时版本。`uv` 明确选择 Python 3.14，并提供构建脚本需要的固定版本 pip；不会把两套分析依赖合并。构建日志会显示实际 Python 版本。参见 [uv 的版本选择说明](https://docs.astral.sh/uv/guides/scripts/#using-different-python-versions)。

构建先校验完整源码，再安装依赖，以便尽早报告缺文件或内容变化。`vercel.json` 的原始字节哈希和 JSON 内容哈希同时登记在发布清单中：缩进、换行和对象键顺序可以变化，但增删字段、改值、调整路由数组顺序及重复 JSON 键都不能通过。构建阶段的其余源码、锁文件、资产和前端产物继续严格校验字节，构建过程不会自动重新封版。

Vercel 的 Python 打包器会移除 `.gitignore`、`web/package-lock.json` 和 `web/public/` 等构建输入。因此运行时不要求这三类文件存在；它们仍登记在发布清单中，并在构建阶段和本地完整校验中检查。平台的 `**/public/**` 规则也会移除 `assets/association/public/` 下的四份分析数据，不能直接将完整资产目录当成实际函数包。打包规则见 [Vercel Python 源码](https://github.com/vercel/vercel/blob/main/packages/python/src/index.ts)。

构建脚本校验全部资产后生成根目录 `runtime-assets.zip`，函数打包排除松散的 `assets/**`。API 入口在导入业务模块之前，将归档中的 60 项文件逐项校验并展开到临时目录，自动设置 `APP_ASSET_DIR`；不需要手动添加这个变量。归档内的目录不会被平台的文件名过滤规则单独移除。缺文件、内容变化和危险路径仍会被拒绝，已有缓存也必须通过校验。构建日志应出现 `Sealed runtime asset archive: runtime-assets.zip (25612256 bytes).`。原 GitHub Release 附件继续使用。

`scripts/check_cloud_bundle.py` 复现四份公共分析数据被移除的情况，并通过实际 API 入口验证归档展开、路径初始化及不调用模型的 live Host 启动，另检查损坏归档、缓存和并发展开。报告为 `cloud-bundle-results.json`。Linux 工作流的五类分析检查也设置 `CLOUD_TEST_ASSET_ARCHIVE=1`，使用从归档展开的数据。运行时代码、知识、模型、数据和发布清单锚点仍严格校验；本地测试通过不替代真实 Vercel 验收。

本项目包含分析依赖、DSH 原生程序和约 226 MiB 解压资产。先前 Vercel 日志报告包体 774.37 MB，超过普通 Python 函数的 500 MB 限制。现在函数改为携带约 24.4 MiB 的资产归档，解压后的数据使用运行时临时空间；最终函数包体仍以新部署日志为准。Large Functions 公开测试版支持至 5 GB，需要 Fluid compute 和 Active CPU。仓库保留 `fluid: true` 和构建环境变量 `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`。参见 [函数限制与启用方法](https://vercel.com/docs/functions/limitations) 和 [Fluid compute 配置](https://vercel.com/docs/fluid-compute)。

这里使用仍受配置规范支持的旧式 `build.env`，仅保存这个公开开关，以兼容导入页面显示 `Populated by System`、无法编辑变量值的情况。官方通常推荐在项目设置中管理环境变量；API 密钥、数据库密码和访问码仍只填写在 Vercel 后台，不能放入此文件。参见 [build.env 说明](https://vercel.com/docs/project-configuration/vercel-json#build.env)。

更新代码后继续部署原项目，不必重建项目或重新上传资产。构建日志应出现 `Vercel large functions build flag: enabled`；它确认构建进程读到了开关，不代表平台资格和最终部署已通过。若仍报告 500 MB，保留该行和完整打包错误，检查项目或团队是否存在同名变量覆盖及平台资格；不要删除模型文件或跳过完整性检查。真正生效与最终包体以 Vercel 的新部署结果为准。

## 6. 填写 Vercel 环境变量

在项目的 **Environment Variables** 添加下面五项，至少勾选 **Production**。每一项都在 Vercel 后台填写，不需要提交 `.env`。

| 名称 | 填什么 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 本机 `.env` 中等号后面的真实密钥，不包含变量名或引号 |
| `DATABASE_URL` | Neon 提供的完整带 SSL 的连接池 URL |
| `APP_ACCESS_CODE` | 后台签名密钥，16～128 个字符，建议随机生成 32 个英数字符；已有值保留即可 |
| `APP_ORIGIN` | 最终网页地址，例如 `https://你的项目名.vercel.app`，不要带页面路径 |
| `ASSET_BUNDLE_URL` | 第 2 步的公开资产 ZIP 下载链接 |

默认是公开体验：分享网址即可，访客不需要注册或输入访问码。`APP_ACCESS_CODE` 沿用原变量名，在公开模式下只用于后台签名，防止访客伪造另一个浏览器的身份；不要删除、公开或发给体验者。浏览器通过首次健康检查自动获得签名 Cookie，然后加载自己的历史。不要设置任何 `VITE_DEEPSEEK_API_KEY` 或将数据库连接字符串放进前端。

可选变量 `APP_ACCESS_MODE` 默认 `public`，无需添加。只有希望改回私密邀请体验时才设置为 `invite` 并重新部署，此时 `APP_ACCESS_CODE` 才同时作为访客输入的访问码。公开模式下旧的 `/_auth` 地址会回到工作台。

首次项目创建时若还不知道准确域名，可先完成创建，查看项目 **Domains**，把真正使用的生产域名填入 `APP_ORIGIN` 后 **Redeploy**。配置不全会显示“云端配置尚未完成”；域名与配置不一致可能返回 403。更换域名后同样更新此变量并重新部署。

预览部署若也要启用，建议使用独立的测试数据库和限额。不要让不同版本同时操作生产账本。生产模式固定使用 DeepSeek；没有密钥时不会自动切成演示模型。

## 7. 部署后逐项验收

首次部署前若还不知道准确域名，可以先填写其余四个应用变量并点击 **Deploy**。构建成功后复制 Vercel 分配的生产域名，设置 `APP_ORIGIN=https://实际域名`，保存并 **Redeploy**。没有填写 `APP_ORIGIN` 时页面显示“云端配置尚未完成”是配置检查的结果，不代表构建失败。不要猜测域名，也不要用部署详情页的控制台地址。

构建和配置完成后直接打开生产地址，再做以下检查。真实分析会产生 DeepSeek 调用费用；先查看云端账本初始限额和供应商账户余额。

1. 新浏览器直接进入工作台，无访问码表单，模型显示 DeepSeek；发送“你好”能得到本地能力提示，不增加模型用量。
2. 输入“比较两个版本的剧情开始情况”，确认过程反馈、最终结果、引用和用量都出现。
3. 追问“那取得资格后，三天还没开始的情况呢？”，检查范围是否延续，是否重新查询本轮证据。
4. 分别测试剧情参与预测、玩家分组、玩法关联、指标解释，检查结果与当前固定数据源一致。
5. 刷新已完成的对话，重新部署同一版本后再打开，确认历史和费用账本仍存在。
6. 删除一个完成的对话，再刷新，确认记录不再出现。另一个浏览器直接进入后应看不到你的历史。
7. 取消一次运行中的任务，等待停止确认。若有未知费用，保护暂停是预期行为，应先核对原因和账单，不直接重置。
8. 用手机通过公网地址打开，再关闭本机的 8765 服务，确认别人仍能使用云端网页。

浏览器关闭或断线可能中断当前分析；页面恢复后查询持久状态，不会自动重复发送付费任务。已完成的结果可恢复，不代表运行中的任务可以无限后台执行。

## 费用与当前范围

目标是 Vercel Hobby + Neon Free，**不购买独立服务器**。但不能提前保证任何访问量都完全免费：账号资格、构建、计算、流量、存储、数据库及 GitHub Actions 均有各自的额度，应以控制台显示为准。DeepSeek API 费用独立于托管平台，不因使用免费托管而免除。

账号注册、数据上传、数据库初始化与部署由仓库维护者手动操作。已有版本的 Linux 验收和 Vercel 部署已通过；本次磁盘占用修复在 Windows 本地通过 16 项打包检查、全部玩家会话核对、五类真实 DSH/MCP 分析及重复统计，模型使用离线桩，采样临时文件占用峰值约 382 MiB。仍须推送后执行新版 Linux 检查、部署并完成上述公网实测。此次修改没有调用付费 API。

公开模式限制每个浏览器在 24 小时窗口内最多提交 10 次分析，同一网络最多 30 次，并将同一网络的全部问题提交限制为 10 分钟内 60 次。窗口从第一次接受请求时开始，不按午夜重置；问候、范围外提示等不占分析次数，但计入提交频率。重复请求不重复扣次数；删除历史或取消已接收的分析不会返还次数。计数保存在现有 `login_limits` 表，并与创建任务在同一事务内完成，不需要增加数据库表。后台只存网络地址的带密钥摘要，不存原始 IP。

清除 Cookie 或更换网络可能绕过单个访客限制，因此全站费用账本仍是模型预算控制：每次付费请求前先预留，预算暂停后不能再发起分析。初始化的 1 元是全站共享总预算，不是每天自动恢复的额度；本次更新不会重置账本或提高限额。

云端目前全站同时执行一项分析，单次执行留出清理时间后最多约 260 秒，平台硬上限为 300 秒。超时或进程丢失不会自动重跑；未结算预留会保留并阻止继续消耗。请求之间只带入最近两轮已核验回答和范围信息，不恢复整个旧 DSH 进程；新一轮数字必须重新取证。

Windows 本地历史不会自动迁移到 Neon；云端新建独立历史。云端保留公开回答、证据、过程事件与费用账本；请求临时目录在成功清理后移除，不提供本地模式那样完整的内部原始运行日志。删除历史不会删除计费记录，数据库供应商的备份保留另受其策略控制。

自选 CSV/Excel 仍只是预览与字段对应，尚不驱动现有分析。Linux 使用进程组管理受控工具链，与 Windows Job 机制不同；Linux 进程回收和平台行为必须由验收确认。

## 常见故障

| 现象 | 先检查 |
| --- | --- |
| `Cloud build requires Linux / Python 3.14` | Build Command 是否为本页完整的 `uv run` 命令；控制台不要覆盖成旧的 `python scripts/build_vercel.py` |
| 构建找不到资产 | `ASSET_BUNDLE_URL` 是否为附件直链、未登录能否下载 |
| source/build/asset integrity 报错 | 是否完整提交本次发布清单、源码、构建清单；除 `vercel.json` 的 JSON 排版外，所有文件仍按字节检查 |
| `JSON content changed vercel.json` | 已排除仅排版不同；核对实际部署提交与项目覆盖配置，保留日志，不删除字段或跳过检查 |
| 包体超过 500 MB | 是否部署了含 `fluid` / `build.env` 的新提交；日志中大包开关是否为 `enabled`；项目变量覆盖与平台资格 |
| 页面显示配置未完成 | 五个应用环境变量是否填写，尤其是实际生产域名 `APP_ORIGIN`；修改后是否 Redeploy |
| 开始分析后立即 `asset_missing` | 在项目 **Logs** 搜索错误摘要的 `job_id`，查看 `analysis_failed` 的具体阶段和文件。若缺少 `association/public/` 数据，确认部署了运行时归档修复且新构建日志出现 `Sealed runtime asset archive`。公开错误文字不能单独证明需要重新上传资产 |
| `close_failed` 或日志 `driver_exit` | 保存同一 `job_id` 下全部 `analysis_failed` 记录，包括 `analysis`、`watch`、`cleanup_host` / `cleanup_coordinator`。新版记录退出码、停止原因、嵌套异常和有界脱敏错误日志；`driver_exit` 本身不能证明内存不足或模型服务故障。不要反复提交已计费问题 |
| `database or disk is full` / `No space left on device` | 临时磁盘不足；确认部署了紧凑会话索引和串行解压更新，并运行新版 512 MiB Linux 验收。增加函数包体上限不能解决运行时磁盘不足；不要重置费用账本或重新上传同一数据包 |
| 新版仍提示输入访问码 | 确认部署了免登录更新且 `APP_ACCESS_MODE` 没有设置为 `invite`；默认公开模式无需输入码 |
| 提示允许 Cookie | 允许此站点保存 Cookie 后刷新，首次健康检查会自动建立浏览器身份 |
| 提示分析次数用完 | 等待相应窗口到期；删除对话不会重置次数，已有结果仍能查看 |
| 503 / 数据库不可用 | Neon 是否初始化了 schema 和预算、连接字符串是否正确且带 SSL |
| 403 | 浏览器生产域名是否与 `APP_ORIGIN` 相同 |
| 分析超时或暂停 | 函数日志、任务事件和费用账本；不要删除账本或自动重发 |

本地开发仍使用 README 中的 `scripts/start-web.ps1`，浏览器地址为 `http://127.0.0.1:8765/`。本次部署的线上地址为 [game-analytic-agent.vercel.app](https://game-analytic-agent.vercel.app)。免登录更新部署后，分享这个地址即可。自行创建其他项目时，以该项目 Domains 中的实际地址为准。
