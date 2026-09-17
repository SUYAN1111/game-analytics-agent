export type Fact = {
  metric_id?:string; kind?:string; field?:string; field_label?:string; raw_value?:number|null; rendered_value?:string;
  unit_label?:string; raw_unit?:string; display_unit?:string; precision?:number; scope?:Record<string,unknown>;
  value?:number|null; unit?:string; denominator?:number|null; selection?:{field:string;scope:Record<string,unknown>};
  antecedent?:string[];consequent?:string[];snapshot_at?:string;text?:string;title?:string;
};
export type Evidence = {id:string;kind:string;label:string;fact?:Fact};
const value=(v:unknown)=>v===null||v===undefined?'缺失 / 不可计算':String(v);
const fmt=(v:number|null|undefined,unit?:string,precision?:number)=>v==null?'缺失 / 不可计算':unit==='%'?(v*100).toFixed(2)+'%':v.toFixed(precision??(unit==='倍'?4:Number.isInteger(v)?0:2));
const fieldNames:Record<string,string>={'player_count':'玩家数','completed_sessions_14d.mean':'近两周人均游玩次数','median_session_minutes_14d.mean':'通常每次游玩时长（组内平均）'};
const metricNames:Record<string,string>={numerator:'获得资格后 72 小时仍未开始',denominator:'能够判断是否开始的有效样本',rate:'72 小时仍未开始的比例',percentage_point_difference:'未开始比例的变化（后一次减前一次）',mean_p:'模型估计的未开始概率（平均）',prediction_coverage:'有预测结果的比例',expected_qualified_count:'应有预测结果的样本',predicted_count:'已有预测结果的样本',missing_count:'没有预测结果的样本'};
const versionLabel=(v:unknown)=>({V1:'第一次更新',V2:'第二次更新',V3:'第三次更新',V4:'第四次更新',V5:'前一次更新',V6:'后一次更新'}[String(v)]||value(v));
const metricLabel=(fact?:Fact)=>metricNames[fact?.field||'']||fact?.field_label;
const scopeValue=(v:unknown)=>({V1:'第一次更新',V2:'第二次更新',V3:'第三次更新',V4:'第四次更新',V5:'前一次更新',V6:'后一次更新',fit_V3main:'第三次更新的玩家习惯记录',discovery_V1_V3:'前三次更新的玩法记录',frozen_t0_replay:'根据历史数据估计',none:'整体'}[String(v)]||(v===null?'整体':String(v)));

export function Results({evidence,onInspect}:{evidence:Evidence[];onInspect:(e:Evidence)=>void}){
  const numeric=evidence.filter(e=>e.kind==='claims'&&e.fact), clusters=evidence.filter(e=>e.kind==='cluster_selections'&&e.fact), rules=evidence.filter(e=>e.kind==='rule_selections'&&e.fact);
  const rates=numeric.filter(e=>e.fact?.kind==='metric_rate');
  const compatible=rates.length>1&&rates.every(e=>e.fact?.raw_unit==='ratio'&&e.fact?.scope?.window_hours===rates[0].fact?.scope?.window_hours&&e.fact?.metric_id===rates[0].fact?.metric_id&&e.fact?.scope?.group_by===rates[0].fact?.scope?.group_by&&e.fact?.scope?.group_value===rates[0].fact?.scope?.group_value);
  const groups=clusters.filter(e=>e.fact?.selection?.field==='player_count');
  const max=Math.max(1,...groups.map(e=>e.fact?.value??0));
  return <div className="result-data">
    {numeric.length>0&&<section><h3>{numeric.some(e=>e.fact?.kind?.startsWith('prediction_'))?'剧情参与预测':'剧情开始情况'}</h3>
      {compatible&&<figure className="bar-chart"><figcaption>已经可以开始剧情，但 3 天后仍没开始的比例</figcaption>{rates.map(e=><div className="bar-row" key={e.id}><span>{versionLabel(e.fact?.scope?.version_id)}</span><svg viewBox="0 0 100 8" preserveAspectRatio="none" aria-label={e.fact?.rendered_value}><rect width="100" height="8" fill="var(--chart-track)"/><rect width={e.fact?.raw_value==null?0:e.fact.raw_value*100} height="8" fill="var(--chart-primary)"/></svg><b>{e.fact?.rendered_value}</b><button onClick={()=>onInspect(e)}>证据</button></div>)}<small>当前比较示例数据中的两次游戏更新。每位玩家在每段剧情中分别计数；比较范围一致，比例越低表示未开始的情况越少。</small></figure>}
      <div className="table-scroll" tabIndex={0} aria-label="剧情开始情况表"><table><thead><tr><th>范围</th><th>统计内容</th><th>结果</th><th>单位</th><th>来源</th></tr></thead><tbody>{numeric.map(e=><tr key={e.id}><td>{e.fact?.scope?.version_id?versionLabel(e.fact.scope.version_id):`${versionLabel(e.fact?.scope?.right_version)} − ${versionLabel(e.fact?.scope?.left_version)}`}</td><td>{metricLabel(e.fact)}</td><td className="number">{e.fact?.rendered_value}</td><td>{e.fact?.unit_label}</td><td><button title={e.id} onClick={()=>onInspect(e)}>查看证据</button></td></tr>)}</tbody></table></div>
      {numeric.some(e=>e.fact?.kind?.startsWith('prediction_'))&&<p className="data-note">这些结果由模型根据历史数据估计，表示“获得资格后 72 小时仍未开始剧情”的可能性，并不是实际发生的结果。没有预测结果的对象不按零计算。</p>}
    </section>}
    {clusters.length>0&&<section><h3>不同玩家，有怎样的游戏习惯？</h3><p className="data-note">下面按游戏习惯分组，比较人数、游玩次数和时长。组名只用于区分玩家，不代表好坏或价值高低。“通常时长”先取每位玩家的游玩时长中位数，再计算组内平均。</p>
      {groups.length>0&&<figure className="bar-chart"><figcaption>每组有多少玩家（人）</figcaption>{groups.map(e=><div className="bar-row" key={e.id}><span>{value(e.fact?.selection?.scope.segment_id)}</span><svg viewBox="0 0 100 8" preserveAspectRatio="none"><rect width="100" height="8" fill="var(--chart-track)"/><rect width={(e.fact?.value??0)/max*100} height="8" fill="var(--chart-secondary)"/></svg><b>{fmt(e.fact?.value)}</b><button onClick={()=>onInspect(e)}>证据</button></div>)}</figure>}
      <div className="table-scroll" tabIndex={0} aria-label="分群特征表"><table><thead><tr><th>玩家组别</th><th>游戏习惯</th><th>结果</th><th>单位</th><th>统计人数</th><th>证据</th></tr></thead><tbody>{clusters.map(e=><tr key={e.id}><td>{String(e.fact?.selection?.scope.segment_id??'全部玩家')}</td><td>{fieldNames[e.fact?.selection?.field||'']||'已分组的玩家'}</td><td className="number">{fmt(e.fact?.value,e.fact?.unit,e.fact?.precision)}</td><td>{e.fact?.unit}</td><td className="number">{e.fact?.denominator==null?'不适用':e.fact.denominator}</td><td><button onClick={()=>onInspect(e)}>查看</button></td></tr>)}</tbody></table></div>
    </section>}
    {rules.length>0&&<section><h3>同一批玩家体验的玩法</h3><div className="table-scroll" tabIndex={0} aria-label="玩法关联数据表"><table><thead><tr><th>体验了这些玩法</th><th>也体验了这些玩法</th><th>统计量</th><th>值</th><th>统计样本数</th><th>范围</th><th>证据</th></tr></thead><tbody>{rules.map(e=><tr key={e.id}><td>{e.fact?.antecedent?.join(' + ')||'整体'}</td><td>{e.fact?.consequent?.join(' + ')||'整体'}</td><td>{{support:'两边都体验过的比例',confidence:'左侧参与样本中也体验右侧的比例',lift:'相对总体的参与比例'}[e.fact?.selection?.field||'']||e.fact?.selection?.field}</td><td className="number">{fmt(e.fact?.value,e.fact?.unit)}{e.fact?.unit==='倍'?' 倍':''}</td><td className="number">{value(e.fact?.denominator)}</td><td>{scopeValue(e.fact?.selection?.scope.evaluation_id)}</td><td><button onClick={()=>onInspect(e)}>查看</button></td></tr>)}</tbody></table></div><p className="data-note">这里统计同一玩家在同一周内体验过的玩法，不代表体验顺序或喜好，也不能证明一种玩法带动了另一种。“统计样本”按玩家和周计数。</p></section>}
  </div>;
}

export function EvidenceView({data}:{data:Record<string,unknown>}){
  const fact=data.fact as Fact|undefined, chunk=data.chunk as {title?:string;text?:string;source_refs?:unknown}|undefined;
  return <><div className="evidence-readable">{chunk?<><h3>{chunk.title}</h3><p>{chunk.text}</p><h4>公开资料来源</h4><pre>{JSON.stringify(chunk.source_refs,null,2)}</pre></>:<><h3>{metricLabel(fact)|| (fact?.antecedent?fact.antecedent.join(' + ')+' → '+fact.consequent?.join(' + '):fieldNames[fact?.selection?.field||'']||'公开统计')}</h3><dl><dt>结果</dt><dd>{fact?.rendered_value??fmt(fact?.value,fact?.unit)}</dd><dt>单位</dt><dd>{fact?.unit_label||fact?.unit||'见公开资料'}</dd><dt>范围</dt><dd>{Object.entries(fact?.scope||fact?.selection?.scope||{}).filter(([k])=>!k.endsWith('_model_id')&&k!=='rule_set_id').map(([k,v])=><div key={k}>{{version_id:'版本',left_version:'左版本',right_version:'右版本',window_hours:'窗口（小时）',group_by:'分组方式',group_value:'分组值',snapshot_id:'数据范围',segment_id:'群编号',evaluation_id:'评价范围',rule_id:'规则编号',time_mode:'时间模式',model_id:'登记模型'}[k]||k}：{scopeValue(v)}</div>)}</dd></dl></>}<p className="data-note">{String(data.limitations||'')}</p></div><details><summary>技术详情与原始数据</summary><pre>{JSON.stringify(data,null,2)}</pre></details></>;
}
