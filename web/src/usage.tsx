export type Usage={mode:string;estimated_cny:number;pending_reserved_cny:number;request_count:number;settled_requests:number;pending_requests:number;input_tokens:number;output_tokens:number;cache_hit_tokens:number;updated_at:number};
export function sumUsage(values:(Usage|undefined)[]):Usage|undefined{
  const rows=values.filter((u):u is Usage=>!!u);if(!rows.length)return;
  const result={...rows[0]};
  for(const key of ['estimated_cny','pending_reserved_cny','request_count','settled_requests','pending_requests','input_tokens','output_tokens','cache_hit_tokens'] as const)result[key]=rows.reduce((sum,u)=>sum+u[key],0);
  result.updated_at=Math.max(...rows.map(u=>u.updated_at));return result;
}
const money=(n:number)=>n>0&&n<.0001?'< ¥0.0001':`¥${n.toFixed(4)}`;
export function UsageDetails({usage,scope='本次',running=false,stale=false}:{usage?:Usage;scope?:string;running?:boolean;stale?:boolean}){
  return <details className={'usage-details '+(scope==='本对话'?'conversation-usage':'turn-usage')}>
    <summary>{!usage?'用量详情':usage.mode==='offline'?'本地模式 · 未调用模型':`${scope}预计成本 ${money(usage.estimated_cny)}`}{usage?.pending_requests?<span className="usage-pending"> · {running?'更新中':'有待确认费用'}</span>:null}{stale&&<span className="usage-pending"> · 更新中断</span>}<span className="usage-chevron" aria-hidden="true">⌄</span></summary>
    <div className="usage-content"><strong>{scope}调用用量</strong>{!usage?<p>尚无用量记录。提交问题后，这里会显示调用情况。</p>:usage.mode==='offline'?<p>当前分析在本地完成，未调用付费模型，因此不计入真实调用成本。</p>:<>
      <dl><div><dt>已记录用量的预计成本</dt><dd>{money(usage.estimated_cny)}</dd></div><div><dt>输入 / 输出 token</dt><dd>{usage.input_tokens.toLocaleString()} / {usage.output_tokens.toLocaleString()}</dd></div><div><dt>其中缓存命中</dt><dd>{usage.cache_hit_tokens.toLocaleString()} token</dd></div><div><dt>模型请求</dt><dd>{usage.request_count} 次 · {usage.settled_requests} 次已记录用量</dd></div>{usage.pending_requests>0&&<div><dt>待确认的请求</dt><dd>{usage.pending_requests} 次</dd></div>}</dl>
      {usage.pending_requests>0&&<p>暂为未确认请求预留 {money(usage.pending_reserved_cny)}，未计入上面的已知成本。{running?'收到模型用量后更新。':'中断或失败不代表免费，预留会保留。'}</p>}
      <p>依据模型返回的实际 token 用量和本地保守单价估算，最终金额以服务商账单为准。这是调用成本，不是向你收取的费用。</p>
      <small>{stale?'连接中断，以下是最后收到的记录':'记录更新时间'} · {new Date(usage.updated_at*1000).toLocaleTimeString('zh-CN')}</small>
    </>}</div>
  </details>;
}
