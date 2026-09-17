# 独立分析 Agent 后端核心（Task14）

本产品是 Windows 本地后端核心，不是网站、HTTP 服务或多用户生产服务。数据为固定模拟数据。
本轮仅迁移及离线验证，没有请求真实模型 API。原实验结论与 Task13 两组 19/24 不变。

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

默认只读资产根为 `<产品>/assets`，可用 `APP_ASSET_DIR` 指向完整解压的资产根。
默认可写状态根为 `<产品>/state`，可用 `APP_STATE_DIR` 指向独立目录。
路径不能彼此覆盖；没有资产或字节校验不符会报错，绝不回退读取实验仓库。
每次启动 Runtime 使用独立 UUID 目录，共享该 Runtime 内的一个预算协调器；每个 Session 有独立 UUID。
不同 Runtime 的预算不共享：不得用新建 Runtime 绕过业务全局限额，网页阶段需独立设计统一账本。

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
Linux/Docker、网页API、任务worker、鉴权、多用户并发、数据库状态迁移、真实模型回复本轮均未验证。
下一阶段应设计 API/worker/界面与状态存储，另行移植和验收 Linux 进程管理及预算通信。
