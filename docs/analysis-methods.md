# 结果旁的分析方法说明

阶段四以本轮已核验证据为入口，结果下方的“分析方法”默认折叠；先显示输入、结果含义与限制，算法和登记身份再折叠一层。说明由产品维护，不是模型生成的推理或新增核验结论。复制和下载时也携带说明，并与核验回答分节。

## 与实际实现的对应

| 结果 | 实际方法 | 核对来源 |
| --- | --- | --- |
| 剧情开始情况 | 72 小时指标的分子、分母、比例与百分点差 | `knowledge_sources/S06/m03_v1.json`、`metrics/m03.py`、本轮 claims 的窗口与 metric_id |
| 参与预测 | 已登记的逻辑回归 lr_c0p1；19 个资格时点输入；不重新训练 | `assets/artifacts/tool_runtime/tools0821fc6e3b48e2cf818e585ddd/cards.json` 的 evaluation、`assets/models/m03/m03ef3c03af2f324e0e12d7ecf37/freeze.json`、`features/contract.py`、`case_adapters/m03_prediction.py` |
| 玩家分组 | K-means 三组，四项近 14 天游玩特征标准化后按已有中心分配；网页读取已有统计 | `assets/segmentation/model.json`、`segmentation/contract.py`、`segmentation/model.py` |
| 玩法关联 | 已有 Apriori 规则及计数复核；按玩家和固定周统计，含完整空样本 | `assets/association/rules.json`、`business_configs/activity_rules_v1.json`、`association/mining.py` |
| 指标与结果说明 | 资料检索和引用核对，没有新增统计 | 本轮 knowledge_selections 和公开来源 |

决策树 tree_d2/d3/d4 是历史候选，不是当前预测器。模型选择记录位于 cards.json 的 analysis_demo.selection；使用验证更新的原始 Brier 距最小值严格小于 0.001 的候选，按预登记次序选首项。页面不制造树图、特征贡献或算法切换开关。

本轮预测证据不带质量评分，故不展示 AUC、准确率或排名；覆盖率不冒充准确率，关联置信度不冒充模型准确率。不在网页训练、挖掘新模型，不声称关联为因果，不增加通用连续值回归功能。

## 证据绑定与兼容

`web/src/analysis-methods.ts` 按证据类型、指标、模型/规则身份和时间模式选择说明，不读取问题文本猜测算法。多类证据分别解释；未知身份、窗口或缺失数据降级为待确认，不沿用已知模型说明。旧历史证据兼容，不迁移数据库、不改变后台协议。

说明中的来源是仓库内可核对的实现或登记文件；“本轮范围”及查看依据按钮使用当前任务自己的证据。查看资料调用已有权限检查和抽屉逻辑，不引入新的资源访问接口。算法说明不触发额外模型调用。

`node web/test-analysis-methods.mjs` 核验登记身份、输入规模、三组和六条规则，并检查未知/混合证据与导出边界。`web/browser-check.mjs` 使用真实 Chrome 和实际分析结果，验证五类说明、默认折叠、键盘展开、证据焦点返回、手机布局、导出与失败时不显示方法。

验收输出在 `state/ux-stage4/`。默认模型仍为离线脚本，真实 DeepSeek 自由提问和自主工具选择尚未联调；四阶段界面验收不代表真实模型验收。
