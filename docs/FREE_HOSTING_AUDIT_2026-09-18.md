# 免费托管可行性检查（2026-09-18）

目标：分享一个网页链接，开发者电脑关机后仍可分析；优先零月租托管，DeepSeek API 另行按量计费。用户已明确跳过性能和 token 优化。本轮检查不改后台业务逻辑、不购买或部署服务、不调用付费 API、不提交或推送 Git。

结论：网页具备使用免费额度的条件；现有完整应用不能原样部署到所查免费平台。零月租完整托管存在候选路线，优先核对 Oracle Always Free 账号和区域是否能获得实例，再进行 Linux 迁移。尚未取得云资源或完成 Linux 实机验收，不能把候选方案称为已免费上线。

## 本地证据

检查版本：`product15afd2e3db6fcc777c75669f77`，60 项资产，`asset143f285f40e8357711e76382ff`。本报告后的发布身份变化仅来自文档和发布清单。

| 检查项 | 实测/核对结果 | 含义 |
|---|---|---|
| 网页成品 | 5 个文件，489597 字节，约 0.47 MiB | 静态网页体积很小；只托管网页不会让后台自动上线 |
| 冻结资产 | 约 225.96 MiB | 不需要 GPU，但部署必须包含资产；它们被 Git 忽略，不能只连接 GitHub 就认为数据已上传 |
| Windows 环境 | core 289.01 MiB、DSH 256.03 MiB | 与资产相加约 771 MiB；不是 Linux 部署包实际体积，不据此直接判定平台超限 |
| 一轮离线真实工具比较 | 成功，约 62.34 秒，0 次付费请求 | 本地模型桩经真实 DSH/MCP 执行；不是云端性能或真实模型测速 |
| 同轮进程内存采样 | 最多 10 个进程；工作集总和峰值 579.76 MiB，私有提交总和峰值 504.76 MiB | Windows 指标，工作集含共享页重复，不能当 Linux 容器用量；512 MB 免费实例缺少已验证的余量 |
| 锁定依赖 | 40 个去重版本中，除 Windows 专用 pywin32 外，其余均有匹配的 Linux x86_64 和 ARM64 wheel | 按 CPython 3.14、glibc 2.39 标签查公开 PyPI；只证明包可选，不证明安装、传递依赖和运行通过 |
| Harness | 0.1.5rc1 提供 manylinux_2_28_x86_64 和 aarch64 运行时包 | 不必因 Harness 只有 Windows 包而放弃 Linux；本项目外围运行控制仍需迁移 |
| 本机 Linux 条件 | 未发现 Docker 命令；WSL 提示尚未安装 | 本轮没有执行 Linux 程序，不安装系统组件或要求重启 |

原始清单、依赖查询、内存样本和复现脚本在 `state/deployment-audit-20260918/`，被 Git 忽略。包文件依据：[PyPI 固定版本清单](https://pypi.org/pypi/deepseek-harness-runtime-bin/0.1.5rc1/json)。内存检查是部署容量摸底，未实施用户已跳过的性能优化。

## 免费方案逐项判断

### Vercel Hobby：网页适合；完整后台需要明显改造

官方当前免费额度包括每月 100 GB 快速数据传输、100 万请求、4 CPU 小时和 360 GB 小时内存；限个人非商业用途。小范围作品网页是合理候选，但账号其他项目共享用量及实际访问量尚未核对。[Hobby 规则](https://vercel.com/docs/plans/hobby)

Python 支持 3.14；Hobby 函数最多 300 秒、2 GB 内存。Python 普通包上限 500 MB，大包 beta 可到 5 GB；还支持容器函数，不能沿用“Vercel 不支持 Python/Docker”或“分析两分钟一定超时”的旧判断。[Python 运行时](https://vercel.com/docs/functions/runtimes/python)、[函数限制](https://vercel.com/docs/functions/limitations)、[容器说明](https://vercel.com/kb/guide/docker)

实际阻碍是当前服务依赖 Windows、跨请求存活的工作线程/子进程，以及本地持久化。Vercel 文件写入建议使用对象存储等持久服务。[文件说明](https://vercel.com/kb/guide/how-can-i-use-files-in-serverless-functions) 迁移需重做任务执行/恢复和状态存储；单纯加配置文件或把数据目录改到临时目录不能保证历史与费用不丢失。免费组合仍可能成立，但本轮没有证明整套后台能适配或落在月额度内，不作为最少改动的首选。

### Render Free：可以托管 Linux 服务，但本项目不宜直接采用

免费计算为 0.1 CPU、512 MB 内存；无请求 15 分钟休眠，重新部署、重启或休眠会丢失本地改写文件。免费服务不能挂持久磁盘，免费 Postgres 30 天到期；免费运行小时每月 750。流量/构建额度也有上限，绑定付款方式后可能产生额外费用。[计算配置](https://render.com/docs/compute-plans)、[免费服务条款](https://render.com/docs/free)

本地单会话采样已显示这一级内存缺少充足余量（不构成 Linux 必然超限的证明），且 SQLite 历史、预算账本和审计证据都依赖本地文件。需迁移存储并实测容量；不能承诺免费实例可靠承载当前应用。

### Hugging Face Spaces：不要把硬件免费误认为账号零费用

当前官方文档写明：新建 Gradio/Docker Space 需要相应付费套餐，CPU Basic 虽标免费，也不等于新账号能零月租创建 Docker 后台。个人账号 PRO 当前为 9 美元/月。默认 16 GB RAM、2 vCPU、50 GB 临时磁盘，依然需处理休眠和持久化。文档另有免费个人账号的 ZeroGPU Gradio 例外，但不是本项目现有 Docker/ASGI 后台的直接部署方式，不据此承诺免费。[Spaces 说明](https://huggingface.co/docs/hub/spaces-overview)、[定价](https://huggingface.co/pricing)

### Oracle Always Free：完整零月租的优先候选，须先核对资格和名额

当前资源文档为 A1 ARM 每月 1500 OCPU 小时、9000 GB 小时，对 Always Free 账号相当于 2 OCPU、12 GB 内存；引导盘与数据盘合计 200 GB 免费额度。不能照旧教程默认分配 4 核 24 GB。Linux 虚拟机和持久磁盘较贴近现有常驻后台/SQLite 结构；结合依赖元数据与本地测量，是本轮最值得验证的免费候选，仍须 ARM 实机测试。[当前资源限制](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

账号注册可能需本人完成银行卡验证，官方称会有临时授权占用；注册成功也不保证所在区域有免费机型。闲置实例可能回收，免费服务无 SLA。Always Free 与 30 天试用赠金不是一回事，不为抢名额升级付费账户，也不通过人为制造负载规避回收规则。[账号与验证说明](https://www.oracle.com/cloud/free/faq/)、[容量与回收规则](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

没有访问用户的云账户；名额、地区网络可用性及用户所在地到服务的访问体验都尚未验证。上述额度是查阅当日规则，实际部署仍核对控制台中的免费标识与合计配额。

## 必须处理的项目阻碍

- `agent_runtime/processes.py`：Windows Job、挂起后启动、子进程归属与整树回收。Linux 需提供等价的进程归属/取消/超时控制，不能删去保护绕过平台限制。
- `web_api/service.py`：Windows `msvcrt` 文件锁、常驻工作线程与会话进程；Linux 需替换锁并维持单实例/单工作线程。
- `agent_runtime/configs/task09_deepseek_v1.json` / `task13_runtime/host.py`：独立环境的 Windows Python 路径；DSH/MCP 进程归属验证也要随平台实现调整。
- `web_api/__main__.py`、`web_api/app.py`：目前只监听且只允许本机地址，Cookie 是本地会话归属，并非公网登录门禁。公开部署需要受控域名、HTTPS、入口鉴权、调用限额以及可信代理配置。
- `product_core/session.py`、预算、SQLite 与运行目录：必须持久化。重启不能使费用归零，未结算请求继续保守保留；不能靠每次启动上传/下载整份 SQLite 代替并发与事务设计。
- 资产、密钥和发布校验：只部署受控构建与登记资产，不上传 `.env`、开发环境、历史 Cookie 或运行日志。云端用平台私密环境变量或服务器私有配置，保持引用及完整性校验。

## 后续顺序与完成标准

1. 先由用户在 Oracle 官方页面核对账号注册和 Always Free 实例是否可获得，不传递银行卡、验证码、密码给助手；账户升级或购买不在本轮授权范围。
2. 有可用资源后，再完成 Linux 兼容实现，在隔离环境执行离线五能力、连续追问、取消、超时、重启恢复、历史删除与预算保留验证；Windows 当前演示保留。
3. 配置持久目录与 HTTPS/访问门禁，用一个公开地址提供前端和 API。可同机托管；若保留 Vercel，采用同源代理设计并验证 Cookie/来源检查，不直接放开跨域。
4. 通过云端小规模验收，确认开发者电脑关机后可访问、重启仍保留历史/账本、控制台用量在免费额度内，再称为免费托管成功。真实 DeepSeek 验收另计 API 费用。

如果无法取得免费实例，再在“进一步改造 Vercel + 外部持久存储”与付费托管之间选择；不先购买服务，也不将付费试用包装成长期免费。本轮没有安装 MySQL，当前单机 SQLite 不因上云就必须更换。
