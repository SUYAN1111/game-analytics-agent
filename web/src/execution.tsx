import type {ExecutionEvent} from './execution-events';
const tools:Record<string,string>={inspect_context:'读取数据范围',check_quality:'检查数据是否可用',query_metric:'统计剧情开始情况',compare_results:'比较两次更新',predict_registered:'读取剧情参与预测',read_model_card:'读取预测说明',get_evidence:'查看数据依据',search_knowledge:'查找指标说明',assign_segments:'查看玩家分组',query_association_rules:'核对玩法参与记录'};
const terminal:Record<string,string>={succeeded:'分析完成，数据已核对',partial:'已完成可支持的部分，数据已核对',clarification:'等待补充信息',out_of_scope:'已确认超出当前能力范围',failed:'本次分析未完成',cancelled:'任务已取消',timed_out:'等待超时，任务已停止',interrupted:'任务已中断',budget_stopped:'本次分析已暂停',close_failed:'暂未能停止任务'};
export function Execution({events,status,disconnected}:{events:ExecutionEvent[];status:string;disconnected:boolean}){
  const active=['queued','running','cancelling'].includes(status);
  const steps=events.filter(e=>e.kind==='progress'&&['preparing','model_started','tool_started','checking'].includes(e.code||''));
  function info(e:ExecutionEvent,index:number){
    const later=events.filter(n=>n.seq>e.seq);
    const label=e.code==='preparing'?'准备分析环境':e.code==='model_started'?'等待分析响应':e.code==='checking'?'核对回答与数据来源':tools[e.tool||'']||'执行分析';
    const outcome=later.find(n=>n.operation===e.operation&&n.tool===e.tool&&n.code===(e.code==='model_started'?'model_finished':'tool_finished'));
    const failed=e.code==='tool_started'&&later.some(n=>n.operation===e.operation&&n.tool===e.tool&&n.code==='tool_failed');
    const done=e.code==='checking'?['succeeded','partial','clarification','out_of_scope'].includes(status):e.code==='preparing'?steps.length>index+1:!!outcome;
    const state=failed?'未取得可用结果':done?(e.code==='tool_started'?'已返回数据':'已完成'):status==='cancelling'?'正在停止':active?(disconnected?'状态待更新':'进行中'):'未完成';
    return {label,state,done,failed};
  }
  const last=steps.at(-1);
  const title=disconnected&&active?'连接中断，正在重新获取状态':status==='queued'?'等待前面的任务结束':status==='cancelling'?'正在停止任务':terminal[status]||(last?info(last,steps.length-1).label:'正在准备分析');
  const body=<ol className="execution-steps">{steps.map((e,i)=>{const s=info(e,i);return <li key={e.seq} data-seq={e.seq} data-code={e.code} className={s.done?'step-done':s.failed?'step-failed':'step-pending'}><span aria-hidden="true">{s.done?'✓':s.failed?'!':'·'}</span><span>{s.label}</span><small>{s.state}</small></li>;})}</ol>;
  if(!active&&!steps.length)return null;
  return <section className="execution" aria-label="执行进展">
    {active?<><p className="execution-current" role="status">{title}</p>{body}<small>{disconnected?'当前显示的是上次收到的记录，恢复连接后会继续更新，不会重新提交问题。':status==='cancelling'?'正在等待后台确认停止，请稍候。':'这里只显示已经开始的步骤，完成后会展示核对过的结果。'}</small></>:<details><summary>查看分析过程 · {steps.length} 步</summary>{body}<p>{title}</p></details>}
  </section>;
}
