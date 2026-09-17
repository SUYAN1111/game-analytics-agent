import type {Evidence} from './results';

// Release-bound descriptions: keep these identities checked against the registered
// assets in test-analysis-methods.mjs. Never infer a model from a question's wording.
export const methodRegistry = {
  metric: 'metric_m03_72h_v1',
  prediction: 'model_m03_lr_c0p1_frozen_v1',
  cluster: 'seg1103fc83512d86a530c698ea46',
  rules: 'rules127bc28f4d855f2eb76d55c9c2',
};
type Description = {title:string; intro:string; inputs:string; reading:string; limit:string; algorithm:string; technical:string; source:string};
const descriptions:Record<string,Description> = {
  metric: {
    title:'剧情开始情况', intro:'先按同一标准统计，再比较比例。',
    inputs:'剧情参与资格、资格获得时间、开始剧情的记录，以及记录是否完整。每位玩家在每段剧情中分别计数。',
    reading:'把“三天内仍未开始”的有效样本数，除以所有能够判断开始情况的样本数。两次更新的变化用后一次比例减去前一次比例，单位是百分点。',
    limit:'无法判断的记录不当作“没有开始”。只有统计范围一致时才适合比较；比例变化本身不能解释原因。',
    algorithm:'比例统计与差值比较', technical:'当前指标观察窗口为 72 小时。这是实际观察记录的汇总，不使用回归模型，也没有检验差异是否具有统计显著性。',
    source:'指标合同与统计实现：knowledge_sources/S06/m03_v1.json、metrics/m03.py。',
  },
  prediction: {
    title:'剧情参与预测', intro:'参考过去的游玩记录，估计三天内仍未开始剧情的可能性。',
    inputs:'只使用获得剧情参与资格时已经知道的信息：近 7 天和 28 天的游玩次数、活跃天数、时长、以往剧情参与情况，以及账号、地区、语言、设备和剧情信息。',
    reading:'模型先为每个玩家与剧情组合估计概率，再汇总展示。平均预测概率不是已经发生的比例；“有预测结果的比例”表示覆盖多少对象，不是准确率。',
    limit:'当前是历史数据上的预测演示，不保证未来表现，也不能说明某个因素导致玩家没有开始剧情。网页使用已有模型，不重新训练。',
    algorithm:'逻辑回归', technical:'当前候选为 lr_c0p1（L2 正则，C=0.1），输入为登记的 19 个字段，正类为获得资格后 72 小时未开始。使用冻结模型按资格时点的信息重放预测；本轮未提供预测质量评分，不展示准确率或效果排名。',
    source:'登记模型卡、模型冻结清单与 features/contract.py；当前模型身份见下方本轮范围。',
  },
  cluster: {
    title:'玩家分组', intro:'把游玩习惯相近的玩家放在一组，再比较各组。',
    inputs:'以数据可确认的历史截止时间为终点，回看 14 天：每位玩家的活跃天数、完成的游玩次数、每次游玩时长的中位数，以及至少 45 分钟的游玩占比。',
    reading:'已有模型把符合条件的玩家分成三组。结果展示每组人数和游戏习惯，方便看出区别；组号只是编号，没有高低排序。',
    limit:'历史不足、记录不完整或没有完成游玩的玩家按数据规则单独处理，不能把分组结果当作全体玩家画像，也不能据此判断玩家价值或流失风险。',
    algorithm:'K-means 聚类', technical:'历史窗口终点取统计时点与最近可见数据水位中的较早者，向前回看 14 天。四项特征先按已有模型的均值和尺度标准化，再按到三个固定中心的距离分配。当前网页读取已有分组统计，不重新寻找中心。展示的“通常时长”是玩家时长中位数的组内平均，不是全组会话的中位数。',
    source:'登记分组模型及 segmentation/contract.py、segmentation/model.py。',
  },
  rules: {
    title:'玩法关联', intro:'看看同一批玩家在一周内还体验了哪些玩法。',
    inputs:'按玩家和固定的一周整理六种玩法的记录：支线体验、地图探索、素材收集、战斗挑战、协作玩法、休闲小游戏。同一玩法反复游玩只记作体验过。',
    reading:'分别看“两边都玩过的比例”“玩过左侧的人中也玩右侧的比例”，以及后者相对于所有样本中右侧参与比例的倍数。',
    limit:'记录完整但没有体验任何玩法的样本也计入总体；记录不完整的样本不参与计算。共现不代表喜好、游玩顺序、因果关系或推荐效果。',
    algorithm:'Apriori 关联规则与计数复核', technical:'已有规则库在前三次更新的记录中发现并保留了六条有方向的规则，后续范围只对既有规则重新计数。本轮仅解释回答中引用的规则，不代表全部玩法关系。支持度 = 同时体验两侧 / 全部有效样本；置信度 = 同时体验两侧 / 体验左侧；提升度 = 置信度 / 右侧总体参与比例。分母为零时不可计算。',
    source:'登记规则库及 business_configs/activity_rules_v1.json、association/mining.py。',
  },
  knowledge: {
    title:'指标与结果说明', intro:'根据已有资料，解释数字的含义和使用范围。',
    inputs:'本轮回答引用的指标定义、模型说明或使用限制。可以打开资料核对原文。',
    reading:'用来理解怎么算、统计了谁，以及能回答什么问题。这一轮资料解释本身没有新增预测、分组或统计结果。',
    limit:'解释不能替代数据分析，也不能作为模型效果或因果关系的证明。',
    algorithm:'资料检索与引用核对', technical:'按本轮已核验的资料引用展示来源；不会因为问题里提到某个算法，就声称实际执行了该算法。',
    source:'本轮公开资料及其来源引用。',
  },
  unknown: {
    title:'方法信息待确认', intro:'这部分结果还没有匹配的方法说明。',
    inputs:'请先查看本轮数据依据中的统计范围。', reading:'保留原始结果，不套用其他模型的解释。',
    limit:'目前无法确认具体算法、输入或质量指标。', algorithm:'尚未登记说明', technical:'证据类型、模型身份或统计窗口与当前说明不匹配。', source:'以本轮数据依据为准。',
  },
};
export type AnalysisMethod = Description & {key:string; evidence:Evidence[]};
export function analysisMethods(evidence:Evidence[]):AnalysisMethod[] {
  const groups=new Map<string,Evidence[]>();
  for(const e of evidence){
    const f=e.fact,s=f?.scope||f?.selection?.scope;let key='unknown';
    if(e.kind==='knowledge_selections')key='knowledge';
    else if(e.kind==='claims'&&f?.metric_id===methodRegistry.metric){
      if(f.kind?.startsWith('prediction_')&&s?.model_id===methodRegistry.prediction&&s?.time_mode==='frozen_t0_replay')key='prediction';
      else if(['count','metric_rate','percentage_point_difference'].includes(f.kind||'')&&s?.window_hours===72)key='metric';
    }else if(e.kind==='cluster_selections'&&s?.segmentation_model_id===methodRegistry.cluster)key='cluster';
    else if(e.kind==='rule_selections'&&s?.rule_set_id===methodRegistry.rules)key='rules';
    groups.set(key,[...(groups.get(key)||[]),e]);
  }
  return Array.from(groups,([key,items])=>({...descriptions[key],key,evidence:items}));
}
export const decisionTreeNote='决策树曾与逻辑回归、历史比例基线一起比较，候选最大树深为 2、3、4。当前选用逻辑回归，决策树没有参与这次预测。选择时使用单独一次更新的验证数据：先筛出 Brier 概率误差接近最小值的候选，再按事先约定的简洁性顺序选择；不是根据当前展示结果临时选模型。';
export function methodMarkdown(evidence:Evidence[]):string {
  const methods=analysisMethods(evidence);if(!methods.length)return '';
  return ['## 分析方法（产品说明）','这些说明解释已登记的方法，不属于模型生成的核验回答。',...methods.map(m=>[
    `### ${m.title}`,m.intro,`使用的信息：${m.inputs}`,`结果怎么看：${m.reading}`,`适用范围与限制：${m.limit}`,
    `算法：${m.algorithm}`,m.technical,m.key==='prediction'?decisionTreeNote:'',m.source,
    '本轮证据：'+m.evidence.map(e=>e.id).join('、'),
  ].filter(Boolean).join('\n\n'))].join('\n\n');
}
