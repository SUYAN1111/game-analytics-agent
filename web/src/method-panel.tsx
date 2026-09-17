import type {Evidence} from './results';
import {analysisMethods,decisionTreeNote} from './analysis-methods';
import './methods.css';

export function AnalysisMethods({evidence,onInspect}:{evidence:Evidence[];onInspect:(e:Evidence)=>void}){
  const methods=analysisMethods(evidence);if(!methods.length)return null;
  return <details className="analysis-methods"><summary><span>分析方法<small>用了什么信息，结果怎么看</small></span></summary>
    <div className="method-content">{methods.map(m=><section className="method-card" key={m.key} data-method={m.key} aria-label={m.title+'的分析方法'}>
      <h4>{m.title}</h4><p className="method-intro">{m.intro}</p>
      <dl className="method-guide"><div><dt>使用的信息</dt><dd>{m.inputs}</dd></div><div><dt>结果怎么看</dt><dd>{m.reading}</dd></div><div><dt>适用范围与限制</dt><dd>{m.limit}</dd></div></dl>
      <details className="method-technical"><summary>算法与技术信息 · {m.algorithm}</summary>
        <p>{m.technical}</p>{m.key==='prediction'&&<div className="method-comparison"><h5>决策树用在哪里？</h5><p>{decisionTreeNote}</p><p>逻辑回归用于估计“是否未开始”的概率；这里没有预测游玩时长、付费金额等连续数值的通用回归功能。</p></div>}
        <p className="method-source">说明依据：{m.source}</p><h5>本轮范围（来自结果证据）</h5>
        <ul className="method-scopes">{[...new Set(m.evidence.map(e=>JSON.stringify(e.fact?.scope||e.fact?.selection?.scope||{})))].map(s=><li key={s}><code>{s}</code></li>)}</ul>
      </details>
      <button className="method-evidence" onClick={()=>onInspect(m.evidence[0])}>{m.key==='knowledge'?'查看本轮引用资料':'查看本轮数据依据'} ↗</button>
    </section>)}</div>
  </details>;
}
