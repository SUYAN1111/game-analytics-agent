export type ExecutionEvent={seq:number;status:string;at:number;kind:'state'|'progress';job_id:string;session_id:string;turn_id:string;code?:string;tool?:string;operation?:string};
type Bound={id:string;session_id:string;turn_id:string};
export function mergeEvents(job:Bound,old:ExecutionEvent[],incoming:ExecutionEvent[]){
  const events=new Map<number,ExecutionEvent>();
  for(const e of [...old,...incoming]){
    if(e.job_id!==job.id||e.session_id!==job.session_id||e.turn_id!==job.turn_id||!Number.isSafeInteger(e.seq)||e.seq<1)continue;
    if(!events.has(e.seq))events.set(e.seq,e);
  }
  return [...events.values()].sort((a,b)=>a.seq-b.seq);
}
