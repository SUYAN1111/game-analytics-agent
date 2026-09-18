# 手动部署到 Vercel

仓库已实现云端代码、数据库持久化、构建配置和 Linux 自动验收。**Windows 本地验证通过；提交 `34a8051` 的 Linux 自动验收已通过，Neon 已完成初始化。首次 Vercel 部署遇到构建 Python 版本不匹配，本次已修正启动命令，等待重新部署；尚未上线。** 具体通过项和限制见 [云端排查记录](CLOUD_VALIDATION_2026-09-18.md)。

网页和分析后台都放在 Vercel；Neon PostgreSQL 只负责保存对话、证据和费用账本。不需要自己购买、维护一台服务器，也不需要 Docker 或 MySQL。DeepSeek 仍使用真实 API，分析数据仍是项目现有的固定模拟数据。

## 1. 将源码提交并推送到 GitHub

由你手动操作。项目根目录是包含 `vercel.json`、`api/`、`cloud_api/`、`web/` 的这一层。

提交本次新增和修改的源码、文档、配置、锁文件、`product_release.json`、`product_core/_release_anchor.py`、`web/build-manifest.json`，以及 `.github/workflows/cloud-acceptance.yml`。不要只提交 `web/`。

现有 `.gitignore` 已排除 `.env`、`assets/`、`state/`、虚拟环境、依赖、构建产物及数据库文件。提交前在编辑器的“暂存的更改”里确认没有密钥和这些目录。不要修改 `.gitattributes` 的 `* -text`：发布校验固定文件字节，自动改换行符会导致云端校验失败。

建议提交说明：`feat: add Vercel backend adapter and persistent cloud storage`。

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
| Fluid compute | 启用 |
| 函数最长时间 | `vercel.json` 已设置 300 秒 |

这些命令已写入 `vercel.json`，控制台不要覆盖成单独的 Vite 前端构建。当前 Vercel Python 支持 ASGI 和流式响应；Hobby Fluid 函数最长 300 秒。参见 [Python 运行时](https://vercel.com/docs/functions/runtimes/python) 和 [函数限制](https://vercel.com/docs/functions/limitations)。

不要将 Build Command 简化为 `python scripts/build_vercel.py`：`Other` 预设下，这可能调用构建镜像的默认 Python，而不是 `.python-version` 所要求的函数运行时版本。`uv` 明确选择 Python 3.14，并提供构建脚本需要的固定版本 pip；不会把两套分析依赖合并。构建日志会显示实际 Python 版本。参见 [uv 的版本选择说明](https://docs.astral.sh/uv/guides/scripts/#using-different-python-versions)。

本项目包含分析依赖和约 226 MiB 解压资产，需使用 Large Functions。该功能当前为公开测试版，支持至 5 GB，并要求 Fluid compute；新建项目自动加入，已有项目可用 `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` 启用。若变量显示 `Populated by System`，无需手动填写或重复添加。最终包体仍须以实际构建结果为准。参见 [官方公告](https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size)。

## 6. 填写 Vercel 环境变量

在项目的 **Environment Variables** 添加下面六项，至少勾选 **Production**。每一项都在 Vercel 后台填写，不需要提交 `.env`。

| 名称 | 填什么 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 本机 `.env` 中等号后面的真实密钥，不包含变量名或引号 |
| `DATABASE_URL` | Neon 提供的完整带 SSL 的连接池 URL |
| `APP_ACCESS_CODE` | 自己生成并保存的随机访问码，16～128 个字符，建议 32 个英数字符 |
| `APP_ORIGIN` | 最终网页地址，例如 `https://你的项目名.vercel.app`，不要带页面路径 |
| `ASSET_BUNDLE_URL` | 第 2 步的公开资产 ZIP 下载链接 |

`APP_ACCESS_CODE` 用于阻止路人直接消耗你的模型额度；分享时把网址和访问码发给指定体验者。访问码不是 DeepSeek 密钥。不要设置任何 `VITE_DEEPSEEK_API_KEY` 或将数据库连接字符串放进前端。

首次项目创建时若还不知道准确域名，可先完成创建，查看项目 **Domains**，把真正使用的生产域名填入 `APP_ORIGIN` 后 **Redeploy**。配置不全会显示“云端配置尚未完成”；域名与配置不一致可能返回 403。更换域名后同样更新此变量并重新部署。

预览部署若也要启用，建议使用独立的测试数据库和限额。不要让不同版本同时操作生产账本。生产模式固定使用 DeepSeek；没有密钥时不会自动切成演示模型。

## 7. 部署后逐项验收

首次部署前若还不知道准确域名，可以先填写其余四个应用变量并点击 **Deploy**。构建成功后复制 Vercel 分配的生产域名，设置 `APP_ORIGIN=https://实际域名`，保存并 **Redeploy**。没有填写 `APP_ORIGIN` 时页面显示“云端配置尚未完成”是配置检查的结果，不代表构建失败。不要猜测域名，也不要用部署详情页的控制台地址。

构建和配置完成后打开生产地址，输入访问码，再做以下检查。真实分析会产生 DeepSeek 调用费用；先查看云端账本初始限额和供应商账户余额。

1. 首页可打开，模型显示 DeepSeek；发送“你好”能得到本地能力提示，不增加模型用量。
2. 输入“比较两个版本的剧情开始情况”，确认过程反馈、最终结果、引用和用量都出现。
3. 追问“那取得资格后，三天还没开始的情况呢？”，检查范围是否延续，是否重新查询本轮证据。
4. 分别测试剧情参与预测、玩家分组、玩法关联、指标解释，检查结果与当前固定数据源一致。
5. 刷新已完成的对话，重新部署同一版本后再打开，确认历史和费用账本仍存在。
6. 删除一个完成的对话，再刷新，确认记录不再出现。另一个浏览器登录后应看不到你的历史。
7. 取消一次运行中的任务，等待停止确认。若有未知费用，保护暂停是预期行为，应先核对原因和账单，不直接重置。
8. 用手机通过公网地址打开，再关闭本机的 8765 服务，确认别人仍能使用云端网页。

浏览器关闭或断线可能中断当前分析；页面恢复后查询持久状态，不会自动重复发送付费任务。已完成的结果可恢复，不代表运行中的任务可以无限后台执行。

## 费用与当前范围

目标是 Vercel Hobby + Neon Free，**不购买独立服务器**。但不能提前保证任何访问量都完全免费：账号资格、构建、计算、流量、存储、数据库及 GitHub Actions 均有各自的额度，应以控制台显示为准。DeepSeek API 费用独立于托管平台，不因使用免费托管而免除。

账号注册、数据上传、数据库初始化与部署由仓库维护者手动操作。当前 Linux 验收已通过，Vercel 首次构建失败后正等待修复版重试。仍须完成上述云端实测，才能确认这套代码在你的免费额度内满足使用需求；构建修复没有新增付费 API 调用。

云端目前全站同时执行一项分析，单次执行留出清理时间后最多约 260 秒，平台硬上限为 300 秒。超时或进程丢失不会自动重跑；未结算预留会保留并阻止继续消耗。请求之间只带入最近两轮已核验回答和范围信息，不恢复整个旧 DSH 进程；新一轮数字必须重新取证。

Windows 本地历史不会自动迁移到 Neon；云端新建独立历史。云端保留公开回答、证据、过程事件与费用账本；请求临时目录在成功清理后移除，不提供本地模式那样完整的内部原始运行日志。删除历史不会删除计费记录，数据库供应商的备份保留另受其策略控制。

自选 CSV/Excel 仍只是预览与字段对应，尚不驱动现有分析。Linux 使用进程组管理受控工具链，与 Windows Job 机制不同；Linux 进程回收和平台行为必须由验收确认。

## 常见故障

| 现象 | 先检查 |
| --- | --- |
| `Cloud build requires Linux / Python 3.14` | Build Command 是否为本页完整的 `uv run` 命令；控制台不要覆盖成旧的 `python scripts/build_vercel.py` |
| 构建找不到资产 | `ASSET_BUNDLE_URL` 是否为附件直链、未登录能否下载 |
| source/build/asset integrity 报错 | 是否完整提交本次发布清单、源码、构建清单；是否被修改了换行符 |
| 包体超过限制 | Fluid compute 和 Large Functions 是否已生效；查看实际包体日志 |
| 页面显示配置未完成 | 五个应用环境变量是否填写，尤其是实际生产域名 `APP_ORIGIN`；修改后是否 Redeploy |
| 503 / 数据库不可用 | Neon 是否初始化了 schema 和预算、连接字符串是否正确且带 SSL |
| 403 | 浏览器生产域名是否与 `APP_ORIGIN` 相同 |
| 分析超时或暂停 | 函数日志、任务事件和费用账本；不要删除账本或自动重发 |

本地开发仍使用 README 中的 `scripts/start-web.ps1`，浏览器地址为 `http://127.0.0.1:8765/`。Vercel 线上地址要等你创建项目后才能确定。
