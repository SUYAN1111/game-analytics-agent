# Task08 受控分析工具与 MCP 合同

代码已编写，等待用户安装依赖并运行验证。本文件说明实现和验收入口，不是运行证据或设计审核批准。

公开输出合同修订代码已编写，等待用户运行验证。本次仅补充指标卡、计数差及 H02/H11/H18/H23 检查；依赖、业务口径与既有登记流程保持不变，旧运行证据保留。

## 入口与职责

七个工具为 inspect_context、check_quality、query_metric、compare_results、predict_registered、read_model_card、get_evidence。
直接 Python 与 MCP stdio 都调用 `analysis_tools.service.Service.dispatch`，共用机器合同、严格参数校验、宿主绑定、证据和聚合实现。
不提供 SQL、任意路径、任意用户筛选、调用方 X、可变时间/窗口、模型参数或运行角色设置。

`runtime_configs/task08_m03_v1.json` 登记本任务书给定的案例、指标、模型、数据与冻结身份、六版主快照、八个查询队列和三个预测队列。
`schemas/analysis_tools_v1.json` 是七工具的实际发现合同，禁止额外字段，不将 bool/int 转成字符串。
指标72h、用户×剧情单位、按区域开放时已注册入候选、四种允许分组均来自本任务书。
检查预期只在 checks 中，不进入配置、指标卡或计算分支。

`inspect_context.data.public_context` 提供完整公开指标卡：meaning、metric（粒度、72h半开窗口、t0、Q5分子、Q4+Q5分母及零分母null）、state_priority、states、time_rules、coverage_rules。
同时提供 targets 派生规则、field_uses、九张 tables 的字段类型/必填/可空、主键及外键关联；这些是字段元数据，不是逐人记录，也不开放 user_id 查询参数。
source_catalog 列出 src01/R1/story_start、src02/R1/session、src03/R2/story_start、src04/R2/session、src05/R3/story_start、src06/R3/session；m03_source_bindings 分别为 R1→src01、R2→src03、R3→src05。
卡片在 Task08 运行配置中按批准的 `business_configs/m03_v1.json`、`schemas/m03_raw_tables_v1.json`、Task01资格状态和Task02/Task03口径投影登记；provenance 保存批准源的SHA-256。原合同不修改，不载入生成配置、潜变量、真值或固定检查答案。原始表合同中的生成计划 main_case 等说明不投影到卡片。
H02 从受保护业务配置/九表合同及事先固定的口径断言逐值核对，不从运行卡片倒填预期；H18 在直接与真实MCP返回中分别核对同一卡片。

## 成熟结果

`case_adapters.m03_tools.M03Backend` 建立本次独立 ObservedIndex，读取已登记九张观测表。只复用 candidates、qualify、story_state 和已验收覆盖函数，不调用 build_features，不读取 Task06 标签或模型结果。
按玩家处理，复用既有会话索引的有界缓存；每个宿主只构建一次候选状态，随后按注册快照、版本与分组聚合。每次调用重新核验获准源文件哈希，源变化时不能继续使用此前结果。
各宿主的本次 SQLite 在其 indexes/ 中，不读取或覆盖历史索引，不加入审核 ZIP。

完整候选包括 Q0/Q1 和没有开始事件的组合。输出每版及跨版按计数合并的总体，不平均各版比例。
M03 分子 Q5，分母 Q4+Q5；分母0时 rate/display_rate 均为 null。
观察覆盖率是 (Q4+Q5)/(Q3+Q4+Q5)，分母0为 null。
存在Q0/Q2/Q3时保留可计算子集及partial提示，不说成全部候选已完整观察。

region_id 按候选开放元数据；有资格者 language/client 按真实 t0，Q0/Q1 按主快照。主案例验证这些属性不变。
new_player 只对 Q2—Q5 按 t0减注册时间小于168小时判断，恰168小时为0；Q0/Q1 为 not_applicable。
group_by 只取一个维度。任何成熟分组有1—19个样本，整项分组视图返回 restricted_granularity 且 rows 为空；不能经比较或证据转读恢复。
没有成熟样本的分组仍保留候选/Q计数，比例为空。固定开发小例由控制器创建豁免宿主，公开参数无法切换。

开始记录的 input_event_rows 是原始上传行数；visible_event_rows 是 event_time和available_at均不晚于快照、去重前行数；deduplicated_event_count 是可见不同event_id数。
资格表另列 input_rows、visible_rows、visible_record_id_count、excluded_rows。
采集/水位表另列 input_rows、visible_rows、deduplicated_records、excluded_rows；正式查询这里是九表数据集中该快照的证据表总量，来源细节见受控审计，不与开始事件相加。

逐候选 population、资格证据ID、真实t0、覆盖结论、区间洞/已知gap及水位比较保存在宿主 audit/。
完整区间版本、历史和快照排除记录每版存一次，候选通过版本和source_id引用，避免为每个玩家复制整份来源历史。
Task02接口的false只是占位，资格审计删除旧“固定样例完整标记”来源，明确标记占位；最终覆盖来自区间与水位。
洞与已知gap分列，不重复相加。source_table_id、registered_python及实际函数路径构成公开可追溯信息，不伪称 SQL 编译。

## 比较

输入只接受本会话的两个 metric evidence_id；验证身份、定义、72h、单位、候选规则、属性规则和分组维度一致，且各为不同的单版本结果。
comparison_key 仅包含总体/分组类型、维度和规范组值，不包含版本；row_key 包含版本。比较返回双方row_key、父内容指纹和右减左差值/百分点。
缺组明确 missing_left/missing_right；空比例不填0。正式固定检查只做事先指定的V5→V6，不搜索差异最大版本。

每一行新增 `count_differences` 对象，固定包含 candidate_count、numerator、denominator、Q0、Q1、Q2、Q3、Q4、Q5 九个字段。每项均为右侧减左侧的整数；两侧分组都存在时，即使任一或双方分母为0，仍计算计数差，rate_difference和percentage_point_difference保持null。
缺少任一侧分组时，九个计数差全部为null，不将缺组当作零计数。比例差为右率减左率，百分点差为比例差乘100，显示精度不替代原值。
H11保留原比较校验并补充九字段、反向、双方零分母和双向缺组的小例；H18核对新增字段双入口一致；H23用独立原始观测复算的计数另算差值并核对比较键及左右行键。检查仍为H01—H24，不改变容差或跳过失败项。

## 冻结预测与模型卡

控制器只用候选元数据和 Task02 资格步骤登记V5/V6无结局队列，核对正面资格在真实t0可见；不从X行数或成熟Q4/Q5反推分母。
每次预测另启本机预测子进程，只传获准 test/X、test/row_map、七项模型、freeze 和无结局队列。不给九张观测表、y、旧概率、成熟查询结果或报告根读取权限。
实际完整调用 `align(X, None, row_map, "test")` 后保留原位置选版本子集；真实使用 `Predictor(assets, asset_hashes)` 加载七项并只预测冻结选中候选。
不重新拟合填补/编码/模型。六类模型与预处理fit方法在执行者内装拒绝守卫；七项参数状态和输入哈希在前后核对。
独立检查器可读旧封存概率做逐样本1e-12绝对误差核对，预测执行者不能读它。

公开预测仅含预期资格数、成功数、缺失数、覆盖率、均值与5个概率桶；不返回用户/样本标识、标签或桶内实际发生率。
逐样本预测以 prediction_as_of=t0、真实 executed_at、registered_model_call、frozen_t0_replay 保存到受控审计。
该时点是冻结重放的特征时点，不能称为已实际部署的首次预测。

模型卡由控制器从SHA绑定的Task07成功 metrics/selection/freeze摘取，再发布给card_reader。
analysis_demo可读七候选在train、V4、V5、V6和合并测试的总体指标、校准桶与选择依据；每项有来源SHA和JSON pointer。
evaluation只得到模型定义、输入要求和冻结信息。请求不得改角色，get_evidence也沿用会话和角色。
不把整份旧报告、逐人预测、旧标签或检查答案变成运行知识库，不重评估或重选模型。

## 授权、证据和传输

宿主资源表按用途精确到逻辑资源，核验真实路径、根目录、链接/目录联接和SHA。日志在本地保留用途、身份、路径和哈希；对外不回显本机路径或原始异常堆栈。
保护哈希不自动赋予工具解析权限。受控审核包和audit不是MCP资源根。上述措施不是OS权限隔离，拥有本机文件修改权的人仍属于信任边界之外。

证据实例ID随机、只在本会话查表，不拼接调用方路径。角色/会话/源身份/内容哈希变化即拒绝。
语义指纹包含规范参数、完整公开内容、质量、身份和父内容指纹；排除request/session/evidence实例ID、时间、transport和路径。
每次实际调用产生独立日志与candidate证据，不缓存预测或复制旧概率。控制器在实际独立核对后另写verified_evidence.json；不写approved/cited。

官方SDK固定为 `mcp==2.2.0`，使用该版本的 MCPServer、Client、stdio_client，以及SDK结构化响应。
源码依据：[官方v2.2.0服务器](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/mcpserver/server.py)、[客户端](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/client.py)、[stdio生命周期](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/stdio.py)。
不使用v1 FastMCP/ClientSession示例、不安装第三方fastmcp、不需要CLI extra，不开HTTP端口。
协议值来自实际协商，wire日志保存SDK真实消息和请求ID；stdout仅协议，进度写stderr。直接入口自己的JSON行协议明确不称作MCP。

初始化等待600秒，工具180秒，预测子进程150秒；30秒心跳不假报进度百分比。
SDK连接关闭会停止自己启动的stdio进程树；检查器持有进程句柄核查实际退出。直接检查进程使用Windows kill-on-close job包含预测子进程。
受控慢小例使用更短客户端期限，只存在宿主测试配置，外部不能触发。取消时先退出调用方取消作用域，再在finally关闭SDK连接，核对PID和活动文件不再变化。
不自动删除任何用户历史缓存。用户Ctrl+C会尽可能保存当前错误和剩余跳过；强制结束终端仍可能留下不完整报告或pending目录。

## 验收与发布

入口只执行本轮H01—H24。生产预期锚点只在checks；全量参考重新读取九张观测表，用原独立Reference的qualification/qstate/meta/covered，另行枚举、归组、计算；不调用Reference.build或生产工具。
正式direct、MCP及登记后重启各自建立本次索引；约69万行会话不再生成，也不放入ZIP。耗时和资源等待用户实测，不预先承诺运行分钟数。

运行目录：artifacts/runs/task08/<run_id>/。及时写各项 result_Hxx.json、progress和原始错误；汇总 acceptance.md、results.json、输入/输出/保护哈希、实际包元数据、完整源码快照。
审核包 review_package.zip包含公开汇总、受控候选/预测证据、独立对账、调用/协议/退出日志及源码合同；不包含原始大表、joblib、SQLite。实算包清单SHA与字节数，校验CRC和成员路径。
原Task01—Task07文件、正式数据与失败报告保持不变；Task08变更清单继承并去重实际保护对象，运行前后均核验。

只有前23项及H24前置符合才能登记candidate/pending。普通宿主拒绝pending，控制器专用启动授权从正式目录重新执行目录、正式查询和真实预测。
报告/ZIP成功后最后原子写ready.json，绑定报告、ZIP、登记清单哈希，不将提交记录塞回这些文件造成自引用。
H24的最终生效需以匹配的正式ready.json为准；没有该记录不能仅凭预提交报告使用工具集。已有同内容ready核验后复用，既有不同内容或未完成pending不覆盖。
工具集ID由源码合同、业务绑定、获准源/模型/模型卡摘要、依赖版本等语义信息产生；不含本次路径、时间或run_id。

## 用户手动执行

在项目根目录，每条单独执行，上一条退出0后再继续：

```powershell
python -m pip install -r requirements-task08.txt
```

```powershell
$LASTEXITCODE
```

```powershell
python -m checks.task08
```

```powershell
$LASTEXITCODE
```

入口自行启动和关闭所需服务，不必预先开其他终端。全部24项符合且无跳过、非预期错误、保护变化，并完成ZIP与ready登记才退出0，否则非零。
依赖缺失/冲突如实报错，不自动安装或升级数值依赖。首次代码交付时安装、程序/测试/预测、MCP握手、取消、登记、报告和ZIP均未运行。

验收后可用实际登记的toolset_id替换占位符：

```powershell
python -m analysis_tools.direct --toolset-id <已登记toolset_id>
```

```powershell
python -m analysis_tools.mcp_server --toolset-id <已登记toolset_id>
```

直接入口从stdin读取name和arguments对象；MCP入口由下一轮宿主通过stdio连接。本轮不接DSH或LLM，不自行进入下一阶段。
