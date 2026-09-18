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

- 本次构建命令修改后的 Linux 重跑；提交 `34a8051` 的 Linux 全部检查已通过，见下方后续记录。当前电脑无可用 Linux/Docker 环境。
- Neon 连接池和云端多实例竞争实测；真实 PostgreSQL 16 的自动化检查已在上述 Linux 运行通过。
- Vercel 成功构建后的路由、原生依赖执行、300 秒截止、内存限制、冷启动、部署包体、断线行为和免费额度消耗。首次 Vercel 构建的失败和修复见后续记录。
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

## 后续 Linux 通过与首次 Vercel 构建

用户提供的 GitHub Actions 截图显示：提交 `34a8051`、分支 `main` 的新运行状态为 Success，总计 3 分 42 秒，Linux 任务 3 分 38 秒，并生成一份验收附件。该工作流包含依赖隔离、HTTP、失败报告、五类真实工具和 PostgreSQL 持久化检查。Node.js Action 弃用提示仍为警告，不影响本次成功状态。Neon 表结构与初始预算也已由用户在 SQL Editor 中初始化并确认。

首次 Vercel 日志显示 `npm ci` 完成，随后执行 `python scripts/build_vercel.py`，因 `Cloud build requires Linux / Python 3.14` 退出。原日志未打印 Python 具体版本；在 Vercel Linux 构建环境中，可确定版本检查没有满足 3.14。`.python-version` 的函数运行时配置不足以保证 `Other` 预设的自定义构建命令使用同一解释器。

修复将构建命令改为 `uv run --no-project --python 3.14 --with pip==25.3 python scripts/build_vercel.py`，明确选择解释器并提供 pip，保留两套 vendor 依赖、资产清单和发布锚点校验。GitHub 工作流也使用相同命令，构建脚本打印实际平台、Python 版本和解释器路径，版本不匹配时给出具体信息。npm 的 audit 和 esbuild 安装脚本警告并非本次退出原因；此次没有使用 `npm audit fix --force` 或变更前端锁文件。

本地隔离测试从 `vercel.json` 读取实际命令，只将最后的构建脚本替换为环境探针：在 `UV_PYTHON=3.12` 下仍选择了 Python 3.14.7，pip 为固定的 25.3；原构建脚本在 Windows 上继续于依赖安装前拒绝执行，并打印实际环境。测试记录在忽略目录 `state/vercel-build-check/environment-result.json`，没有调用付费 API。该测试确认版本选择与 pip 可用，不代替完整 Linux 构建。

本次修复尚待真实 Vercel 重新构建与公网验收；Linux CI 成功不等于 Vercel 已部署成功。此前的资产 ZIP、Neon 数据和 Vercel 环境变量继续复用。

## Vercel 配置文件完整性失败

用户随后提供的日志显示，提交 `834e2a0` 已通过 Python 检查、依赖安装、资产步骤和前端构建，在构建脚本最后的 `verify()` 中报 `product_integrity: missing/changed vercel.json`。只读查询 GitHub 确认：远端 `main` 与最近部署均为 `834e2a09296c39e32bc626e054a4ee9d32d002ef`，远端 `vercel.json` 字节与该提交的发布清单一致；本地全部 336 项源码也与 Git 提交字节一致。可排除漏提交和本地清单失配。

当前证据确认构建环境中的配置未满足字节校验，但没有取得该环境的实际配置内容，不能断言仅发生了排版变化。现有校验会将 JSON 压缩、缩进、换行或对象键顺序调整一律视为改动，缺少对等价序列化的兼容。

本次显式封版时额外登记 `vercel.json` 的规范 JSON 哈希，并保留原字节哈希。运行时只有该文件可在字节不一致时回退到全量 JSON 内容校验；不忽略任何字段，不接受额外字段、重复键、非有限数或数组顺序变化。业务源码和资产仍按原字节校验，发布锚点继续生效。校验移至安装依赖前，并在全部构建完成后重复检查；真正配置内容改变时会明确报 `JSON content changed vercel.json`，不会修改云端文件或重算发布锚点强行通过。

新增 `scripts/check_release_integrity.py` 在独立源码副本上验证格式等价与负向篡改场景，并加入 Linux CI。18 项本地检查全部通过，包括原文件、压缩 JSON、CRLF、键重排，以及路由/请求头/时限/字段/类型变化、非法 JSON、重复键、缺文件、其他源码字节变化、将 JSON 例外套用到资产和清单锚点被改等拒绝场景。报告为忽略目录中的 `state/release-integrity-results.json`。此次未调用付费 API，尚待实际 Vercel 重试确认失败是否仅由序列化差异引起。

## Vercel 函数包体超过 500 MB

用户后续日志显示 `Total bundle size (774.37 MB) exceeds the maximum function size (500 MB)`，说明部署已进入 Python 函数打包阶段。当前阻塞是包体限制。只读核对官方 Python 打包器的 `dependency-externalizer.ts` 与 `large-functions.ts`：这条 500 MB 错误位于未开启 Large Functions 的分支，开关读取构建进程的 `VERCEL_SUPPORT_LARGE_FUNCTIONS`，仅 `1` 或 `true` 会启用。官方的 Large Functions 公开测试版支持至 5 GB，但需要 Fluid compute 与 Active CPU；不能将新项目的默认资格当作该项目已生效的证明。参见 [函数限制](https://vercel.com/docs/functions/limitations)。

配置新增 `fluid: true`，并在 `build.env` 中仅加入公开开关 `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`。该旧式字段仍在官方配置规范中，用于将环境变量传入构建进程；因用户导入界面的值不可编辑且找不到 Functions 开关，采用仓库配置以减少手动步骤。应用密钥、数据库凭据和访问码仍留在项目后台，未写入源码。构建脚本只打印开关是否启用，不打印环境变量集合。参见 [构建环境变量说明](https://vercel.com/docs/project-configuration/vercel-json#build.env) 和 [运行时构建环境](https://github.com/vercel/vercel/blob/main/DEVELOPING_A_RUNTIME.md#accessing-environment-and-secrets)。

本地按官方 JSON schema 的字段约束校验完整配置，并确认无效的 `fluid` 字符串会被拒绝。官方 schema 混用了 draft-04 声明和新版本队列约束，校验采用 Draft7 的实例验证，不声称通过官方 schema 自身的元验证。运行下载的官方 `isLargeFunctionsEnabled()` 确认仓库开关被接受，并用缺失值、`0` 作负向对照；这不是一次 Vercel 部署。报告在忽略目录 `state/vercel-size/`。

此次没有裁剪冻结资产、合并两套 Python 依赖、变更分析工具或新增付费 API 调用；没有提交、推送或操作远端项目。仍需用户推送后，在原 Vercel 项目确认日志出现 `Vercel large functions build flag: enabled`，再确认最终部署成功及公网功能。构建进程读到开关不等于平台已接受大包或云端运行验收通过。

## Vercel 部署成功与首屏登录引导（后续改为默认公开体验）

用户截图确认提交 `bd33501` 的生产部署已 Ready，正式地址为 `https://game-analytic-agent.vercel.app`。用户补齐生产环境的 `APP_ORIGIN` 并重新部署后，页面由“云端配置尚未完成”变为“请刷新页面并输入访问码”，但没有显示表单。

只读 HTTP 实测确认：`/` 返回 200 静态工作台 HTML；`/_auth` 返回 200，包含实际访问码表单；`/api/health` 返回 `401/access`。这说明首页直接提供静态壳，后台认证仍然生效，单纯刷新首页无法打开登录表单。此次检查没有提交公网登录表单，也没有读取或索取用户访问码。

前端收到明确的 `401/access` 后使用 `location.replace('/_auth')` 进入固定同源的访问码页，不接受返回数据指定跳转地址，也不重试或重放被拒绝的操作。服务初始化失败时，左下角显示“服务连接失败”与错误颜色；其他 401、配置 503 不会误跳转。后台访问码、浏览器身份隔离、预算和数据权限均未改变。

`scripts/check_cloud_login_browser.mjs` 使用真实无头 Chrome、临时本地 PGlite / Cloud API 和固定测试访问码 `local-cloud-test-access`。浏览器故意用构建后的静态 HTML 覆盖首页，以复现 Vercel 的访问路径，再验证自动跳转、真实表单登录、API 可用、刷新不循环且 owner 稳定、登录过期重新验证、配置 503 与其他 401 不跳转。7 项检查全部通过，无浏览器脚本异常，无分析任务提交，`paid_calls=0`。本地临时 API 默认地址为 `http://127.0.0.1:8767`（可用 `CLOUD_LOGIN_TEST_ORIGIN` 修改，仅接受回环地址），需要已安装的 Chrome 及网页依赖；验证入口为 `node scripts/check_cloud_login_browser.mjs`。报告与截图在忽略目录 `state/cloud-login/`。

前端 TypeScript / Vite 构建通过。以上为私密邀请模式的验证记录；用户随后要求简历体验免输入码，当前实现及待部署范围以下节为准，不将本地浏览器成功表述为已完成云端分析测试。

## 简历作品默认免登录访问

用户要求 HR 打开链接后直接使用。`APP_ACCESS_MODE` 缺省改为 `public`，保留可选 `invite` 模式。原 `APP_ACCESS_CODE` 在公开模式下仅用于后台 HMAC 签名；已有五项环境变量保留，不需要新建项目、上传新资产或修改 Neon schema。生产入口仍固定使用真实 DeepSeek，不接受环境变量将其切换为离线桩。

首次健康检查自动设置签名、HttpOnly 的浏览器身份，再由前端加载历史。直接访问静态首页也能完成这一步，避免首页由 CDN 提供时看不到访问入口。伪造签名被拒绝，跨浏览器记录隔离不变；已有有效邀请会话迁移到公开模式时保留历史。旧 `/_auth` 在公开模式下回到工作台，原前端 `401/access` 跳转仅供可选邀请模式使用。

公开分析限额为每浏览器 24 小时 10 次、同一网络 24 小时 30 次；同一网络全部问题提交在 10 分钟内最多 60 次。使用现有 `login_limits` 表，在创建任务的同一个全局锁事务内计数；超额回滚，重复提交不重复计数，取消和删除历史不退款。仅在 Vercel 环境读取平台管理的 `x-vercel-forwarded-for`，本地环境忽略转发头；数据库保存带密钥的网络摘要，不保存原始 IP。平台头依据见 [Vercel 请求头说明](https://vercel.com/docs/headers/request-headers)。这些限额不能代替身份认证，全站模型费用预留和预算暂停继续生效，未提高或重置线上预算。

`scripts/check_cloud_public.py` 在临时本地 PostgreSQL 兼容实例上通过 12 项检查：默认公开入口、首次身份建立与并行稳定性、签名伪造与归属拒绝、幂等和排队回滚、浏览器/网络限额、窗口到期与问候频率、预算暂停、两个独立 Service 实例竞争最后一个名额、可选邀请模式及历史迁移、网络摘要和费用账本不变、生产模式不受测试变量影响。已加入手动 Linux 工作流，新增代码的 Linux 运行待用户推送触发。原 `scripts/check_cloud_http.py` 显式使用邀请模式，原有私密访问回归也通过。

`scripts/check_cloud_login_browser.mjs` 更新为公开体验浏览器检查，历史文件名保留。真实无头 Chrome 从模拟 CDN 的静态首页进入，API 使用临时本地 Cloud API，先确认 `offline` 模式后提交问候和版本比较。10 项检查通过，真实 DSH/MCP 比较产生 7 项证据；刷新恢复、390×844 手机布局、跨浏览器拒绝、实际删除、旧入口跳转、服务错误提示均通过，无脚本异常。报告与截图在忽略目录 `state/cloud-public-browser/`，`paid_calls=0`。该脚本仅接受回环地址，需要已安装的 Chrome、网页依赖及临时 API，执行命令仍为 `node scripts/check_cloud_login_browser.mjs`。

此轮没有读取生产密钥、访问码或数据库凭据，没有操作公网账户、提交或推送代码，也没有运行公网付费分析。更新推送并在原 Vercel 项目部署后，还需验证实际生产网址可免登录完成 DeepSeek 分析。

## Vercel 打包后的文件校验失败

免登录版本已提交为 `df59e03`。用户提供公网任务 `abc6e4dd8d5642558881b6ecf45280c5` 的错误摘要：`asset_missing`，约 4 秒失败，页面显示预计成本为零。该错误是 `asset_integrity` / `knowledge_integrity` 的通用映射，公开摘要没有包含具体文件。

对照 [Vercel Python 打包器](https://github.com/vercel/vercel/blob/main/packages/python/src/index.ts) 的 `predefinedExcludes`，发现平台默认移除 `.gitignore`、`**/public/**` 和 `**/package-lock.json` 等文件。当前完整源码清单包含其中 107 个文件。将发布源码复制到临时目录并按这些规则移除后，原校验稳定报 `product_integrity: missing/changed .gitignore`。原 Linux CI 和浏览器测试使用未打包目录，因此没有覆盖此差异；没有取得该次公网任务的内部堆栈，不能声称已逐项核对其线上文件清单。

修复将构建校验与运行时校验区分：`verify(..., include_build_sources=True)` 仍要求完整已封版源码；构建前后、本地 `product_core verify` 及前端构建校验显式使用完整模式。默认运行时校验仅免除 `.gitignore`、`web/package-lock.json` 和 `web/public/`，不对其他缺失文件自动放行。代码、知识资料、模型、分析数据及发布清单锚点仍按原规则核验。

新增 `scripts/check_cloud_bundle.py`，按独立的平台排除规则复制封版文件及真实资产，9 项检查通过：运行时校验、完整构建拒绝缺文件、运行代码与知识变更拒绝、模型缺失/变更拒绝、清单锚点、打包目录中 live Host 的真实资源初始化，以及后台日志脱敏。live Host 没有调用 `open` 或发送模型请求；该检查已加入 Linux 工作流，Windows 本地通过，新版 Linux 运行待推送触发。完整发布完整性 18 项和前端产物校验也通过。

另在临时本地 PostgreSQL / CloudService 中执行一次版本比较，使用离线模型桩及真实 DSH/MCP，返回 `succeeded`、7 项证据、无分析错误；报告 `state/cloud-bundle-analysis.json`。离线桩的请求也会登记在临时账本中，不代表真实 DeepSeek 用量。本次没有使用生产密钥或付费模型；测试对话已清理，生产预算未修改。

后台新增有界脱敏的 `analysis_failed` 日志，保留任务 ID、失败阶段和具体原因，以便在 Vercel **Logs** 排查。API、前端和复制错误摘要仍只返回通用错误，不包含内部路径、密钥或原始工具数据。此次修复待手动推送部署，公网真实 DeepSeek 分析仍需验收。

## 公网日志确认分析资产被平台过滤

继 `97e2851` 的修复后，用户提供任务 `a859c8cb93814ad1a6a2d240009d6791` 的 Vercel 私有日志：`stage=prepare`、`type=HostError`、`code=asset_integrity`，具体为 `product_integrity: missing/changed association/public/discovery_V1_V3.json`。这确认了实际分析资产缺失。上一轮模拟测试只对源码应用平台过滤规则，却完整复制了资产，因而漏掉此场景。

Vercel Python 打包器的 `**/public/**` 规则同时影响四个已封版的资产文件：`association/public/discovery_V1_V3.json`、`validation_V4.json`、`validation_V5.json`、`validation_V6.json`（后面三项同目录），合计 17,586 字节。本轮测试先对源码和资产都应用规则，稳定复现日志中的同一文件错误，再验证修复。

新增 `cloud_api/asset_bundle.py`。构建完成完整校验后，将原 60 项资产生成单个 `runtime-assets.zip`；`vercel.json` 排除松散的 `assets/**`，保留归档。API 入口在业务路径模块导入前校验发布锚点、检查归档清单和每项大小、哈希，展开到系统临时目录并设置 `APP_ASSET_DIR`。状态目录与资产目录保持独立。展开使用独立暂存目录及原子发布；并发启动可复用已完整验证的目录，损坏缓存不放行。

资产身份仍为 `asset143f285f40e8357711e76382ff`，归档仍为 25,612,256 字节、SHA-256 `455b9f3f40ef0b08957c716d34c5a62b2846b402466491e0a76f94211cb294b2`，与原 GitHub Release 附件相同。无需新附件、环境变量、数据库初始化或访客访问码。

本轮 Windows / Python 3.14 本地验证：

- `scripts/check_cloud_bundle.py` 的 15 项检查通过：复现原始缺失、完整构建拒绝漏文件、源码/知识/模型/清单变化拒绝、全部 60 项资产恢复、坏归档和危险路径拒绝、并发及缓存校验、实际 `api.index` 在无松散资产的目录中启动 live Host、私有日志脱敏。live Host 仅初始化，不调用模型。
- `CLOUD_TEST_ASSET_ARCHIVE=1` 下的 `scripts/check_cloud_runtime.py` 连接临时本地 PGlite，使用归档展开的数据、离线模型桩及真实 DSH/MCP。比较、知识、预测、分群、关联全部 `succeeded`，分别产生 7、2、5、10、3 项证据，诊断列表为空。每类均检查新 Service 读取持久结果和删除。报告 `state/cloud-runtime-results.json` 为 `PASS`，`assets_from_archive=true`、`paid_calls=0`。
- 18 项发布完整性检查通过；完整源码、60 项资产及前端产物校验通过。发布清单仅在本地显式重新封版，云端构建不重算信任锚点。

Linux 工作流新增从运行时归档执行五类分析的步骤，待用户推送后运行。本轮没有提交、推送、部署、调用真实 DeepSeek 或修改生产预算。上述结果不能替代新版本的 Vercel 冷启动、实际函数包体、Neon 连接池及公网真实模型分析验收。

## 分析子进程退出与清理错误被掩盖

用户提交 `5be7190` 后，任务 `a4cf85bf5fc84f84be94ca085fd4e7b9` 在约 33 秒后显示 `close_failed`，页面预计成本为 ¥0.0055。用户确认一直等待，没有主动结束、取消、刷新或关闭页面。Vercel 日志为 `stage=analysis`、`type=HostError`、`code=driver_exit`、`message=DSH driver closed without a completed response`。这只能确认分析子进程未返回完整响应，不能确认是内存、供应商、数据库监控或其他平台问题。

代码审查确认原错误处理会用清理失败覆盖公开错误状态，却只记录先前的分析异常；Host 内的 ExceptionGroup 仅打印概括，后台监控线程的异常也被吞掉。第一项资源关闭失败后，后续 Coordinator 和测试 Stub 不再关闭。云端“再次点击结束对话”的提示也不适用于已结束请求的进程清理。

本轮分别记录分析、后台监控和每项资源关闭的错误，保留最多 12 个嵌套原因、进程退出码及停止原因。私有日志只读取控制器 stderr、driver_errors 和 MCP stderr 的有界尾部，并脱敏；不记录配置、模型 stdout、回答或工具结果，不向公开 API 增加内部诊断。每项资源独立执行关闭。清理未确认的执行仍保持未完成标记，点击关闭不会假装已释放；超过原有执行期限后标记为中断，保留未知费用并禁止自动重放。未更改模型、预算、工具和进程归属规则。

Windows 本地 `scripts/check_cloud_cleanup.py` 的 7 项检查通过：真实子进程以 23 退出、嵌套清理异常脱敏、原始与清理错误分别保留、其余资源继续关闭、未确认执行与到期中断、数据库监控异常导致的自动停止记录、没有模型预留及预算限额变化。报告为 `state/cloud-cleanup-results.json`，`paid_calls=0`，该检查加入 Linux 工作流。

原始启动失败的诊断检查继续通过；从归档展开数据的五类真实 DSH/MCP 分析也全部成功，证据数为 7、2、5、10、3，使用本地离线模型桩、临时 PGlite，诊断列表为空。没有访问生产数据库、读取生产密钥或调用付费模型。本轮尚未解决线上子进程退出的根因，需要部署诊断更新后取得同一任务完整的 `analysis_failed` 记录，不能将本地回归通过表述为线上问题已修复。

## 完整日志确认临时磁盘不足，改为紧凑索引

用户展开任务 `54e0688bc46c4a3daee36ba705d1da93` 的 `runtime` 后，MCP 错误日志明确显示：`query_metric` 在为 `session_uploads` 创建 SQLite 索引时，处理到约 600,000 行后报 `sqlite3.OperationalError: database or disk is full`。随后错误审计文件和 `budget.json` 镜像写入也报 `OSError: [Errno 28] No space left on device`，最终表现为 `driver_exit` 和 `close_failed`。这份日志确认了磁盘原因，不再将其归因于未证实的内存、用户取消或模型服务错误。

对同一封版资产集的修改前实测：解压后 60 个资产共 **236,939,741 字节**，完整 JSON 行索引 **358,129,664 字节**，两者合计约 **567.5 MiB**，尚未包含索引排序临时文件和请求记录。数据包上传正确并不代表其解压后与索引的总占用能放进云端临时磁盘。

`features/observed.py` 改为在 SQLite 中保存会话 JSONL 的字节位置和长度；读取时从已校验的原始文件取回记录，并使用相同字段和 UTC 规范化校验。不重复保存整行 JSON，也不在按玩家查询的索引里重复保存长上传 ID。保留上传 ID 唯一约束、逻辑会话的跨归属检查、排序和 16 名玩家缓存上限。小型显式测试样例继续支持内存输入。完整索引现为 **138,526,720 字节，约 132.1 MiB**，较原版少约 **61%**。没有删减玩家、会话、字段或分析步骤。

`cloud_api/asset_bundle.py` 使用进程间操作系统锁，串行安装同一资产缓存，避免两个冷启动同时解压各自的完整数据。锁随进程退出释放，缓存仍逐项验证资产大小和 SHA-256，损坏数据不会被忽略。原资产附件、资产集标识、五个应用变量、Neon schema 和费用限额保持不变。

Windows 本地验证：

- `scripts/check_observed_storage.py`：5 组检查通过。全部 **690,103** 条会话、**5000** 名玩家的规范化查询结果与修改前索引逐一一致，聚合摘要为 `5bf82acb0193626237d877bf786afd48bd2f92f805bfd2b9cbb86078565868bd`；覆盖多字节字符、CRLF、无末尾换行、UTC 排版、乱序、逻辑 ID 跨归属、缓存淘汰、重复上传拒绝及 SQLite 容量错误路径。
- `scripts/check_cloud_bundle.py`：16 项通过，含两个独立进程同时安装时只出现一份解压暂存目录，以及真实 API 入口初始化。
- 从归档展开资产后，真实 DSH/MCP 五类工具及第二次剧情统计全部成功，证据数依次 **7、2、5、10、3、7**，诊断列表均为空，完成任务目录均被回收。本地模型使用离线桩，临时 PGlite 保存费用和结果，`paid_calls=0`。
- 按 4 KiB 分配单位、50 ms 间隔采样资产与任务临时文件，峰值 **400,535,552 字节，约 382 MiB**。这是 Windows 文件占用采样，不等同于已验证 Vercel 的文件系统配额；报告为 `state/cloud-storage-runtime/cloud-runtime-results.json`。
- 发布完整性 18 项检查通过。运行时资产与源码仍由发布清单绑定，未跳过校验、云端重封版或切换生产模型。

为覆盖此前本地大磁盘漏掉的约束，手动 Linux 工作流新增 **512 MiB tmpfs**，将解压资产、请求目录及子进程临时目录全部置于其中，再执行上述五类分析与一次重复统计。测试会核实实际磁盘容量，输出峰值文件占用和文件系统实际占用，并上传报告。本机未安装 WSL/Linux，当前只完成 Windows 验证；该受限文件系统检查与更新后的真实 Vercel/DeepSeek 分析须在用户推送后完成。不能将本地成功表述为生产已恢复。
