import {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import Markdown from 'react-markdown';
import './style.css';
import './workspace.css';
import './flow.css';
import './execution.css';
import './scope.css';
import './fonts.css';
import './studio.css';
import {UsageDetails,sumUsage,type Usage} from './usage';
import {useReducedMotion,usePresence,useAutoInput,DirectionSelection} from './motion';
import {Execution} from './execution';
import {mergeEvents,type ExecutionEvent} from './execution-events';
import {ResultOverview} from './result-overview';
import {AnalysisMethods} from './method-panel';
import {methodMarkdown} from './analysis-methods';
import {Results, EvidenceView, type Evidence} from './results';
import {BrandMark} from './brand';
import {DataSource} from './data-source';

type Job = {id:string; session_id:string; turn_id:string; text:string; status:string; created:number; updated:number;
  answer:{answer_markdown:string; status:string; message?:string; choices?:{text:string}[]; limitations?:string[]}|null; error:{code:string; message:string}|null;
  routing?:{kind:string;message?:string;limitations?:string[]}|null;
  execution_mode?:'request'; usage?:Usage; evidence:Evidence[]; events:ExecutionEvent[]};
type Session = {id:string; title:string; status:string; created:number; jobs?:Job[]};
type Health = {mode:string; period:string; mode_label:string; questions:string[]; fault_questions:string[];
  capabilities:{title:string;description:string;examples:string[]}[];
  budget:{stopped:boolean}};
const active = (j:Job) => ['queued','running','cancelling'].includes(j.status);
const labels:Record<string,string> = {queued:'排队中',running:'正在分析',cancelling:'正在停止分析',succeeded:'分析完成 · 数据已核对',
  partial:'部分完成 · 已有结果已核对',clarification:'需要补充信息',out_of_scope:'当前能力范围之外',guidance:'使用提示',
  failed:'未完成',cancelled:'已取消',timed_out:'已超时',budget_stopped:'分析额度已暂停',interrupted:'任务中断',close_failed:'暂未能结束'};
async function api<T>(path:string, body?:unknown):Promise<T> {
  let response:Response,value;
  try{response=await fetch('/api'+path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});value=await response.json();}
  catch{throw new Error('暂时无法连接服务，请稍后重试。');}
  if (!response.ok) {
    // Vercel can serve the static shell before the Python homepage route.
    // The API remains authoritative; never retry or replay a rejected action.
    if(response.status===401&&value.error?.code==='access'){
      window.location.replace('/_auth');
      throw new Error('正在打开访问验证…');
    }
    throw new Error(value.error?.message || '服务暂时不可用，请稍后再试。');
  }
  return value;
}
function SafeMarkdown({text}:{text:string}) {
  return <Markdown skipHtml disallowedElements={['img']} urlTransform={url=>/^https?:\/\//i.test(url)?url:''}
    components={{a:({children,href})=><a href={href} target="_blank" rel="noreferrer noopener">{children}</a>}}>{text}</Markdown>;
}
const definitionGuide='这里统计的是：获得剧情参与资格后，72 小时内仍未开始的比例。只纳入能够判断开始情况的有效样本；同一玩家在不同剧情中分别计数。比例越高，表示未开始的情况越多。';
const predictionGuide='模型根据玩家获得参与资格时已有的信息，估计之后 72 小时仍未开始剧情的可能性。当前展示的是历史数据上的预测演示，不能当作已经发生的结果，也不能保证未来一定如此。';
const guides:Record<string,string>={'剧情开始情况是怎么算出来的？':definitionGuide,'M03 的分子分母和适用范围是什么？':definitionGuide,'这些预测结果该怎么看？':predictionGuide,'冻结预测是什么意思？':predictionGuide};
function KnowledgeAnswer({job}:{job:Job}){return guides[job.text]?<><p className="plain-guide">{guides[job.text]}</p><details className="verified-text"><summary>查看完整说明与来源原文</summary><SafeMarkdown text={job.answer?.answer_markdown||''}/></details></>:<SafeMarkdown text={job.answer?.answer_markdown||''}/>;}
function App(){
  const cloudRuns=useRef(new Set<string>());
  const reducedMotion=useReducedMotion();
  const [menuOpen,setMenuOpen]=useState(false);
  useEffect(()=>{
    const resized=()=>{if(innerWidth>760)setMenuOpen(false);};
    const close=(e:KeyboardEvent)=>{
      if(e.key==='Escape')setMenuOpen(false);
      if(menuOpen&&e.key==='Tab'){
        const buttons=Array.from(document.querySelectorAll<HTMLButtonElement>('.sidebar button')).filter(b=>!b.disabled&&b.offsetParent!==null);
        const first=buttons[0],last=buttons.at(-1);
        if(first&&last&&((e.shiftKey&&document.activeElement===first)||(!e.shiftKey&&document.activeElement===last))){e.preventDefault();(e.shiftKey?last:first).focus();}
      }
    };
    window.addEventListener('resize',resized);window.addEventListener('keydown',close);
    if(menuOpen)document.querySelector<HTMLButtonElement>('.sidebar .new-button')?.focus();
    return()=>{window.removeEventListener('resize',resized);window.removeEventListener('keydown',close);if(menuOpen&&innerWidth<=760)document.querySelector<HTMLButtonElement>('.menu-toggle')?.focus();};
  },[menuOpen]);
  useEffect(()=>{
    const close=(event:PointerEvent|KeyboardEvent)=>{
      const panel=document.querySelector<HTMLDetailsElement>('.conversation-usage[open]');
      if(panel&&(('key' in event&&event.key==='Escape')||(!('key' in event)&&!panel.contains(event.target as Node))))panel.open=false;
    };
    document.addEventListener('pointerdown',close);document.addEventListener('keydown',close);
    return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',close);};
  },[]);
  const [health,setHealth]=useState<Health|null>(null), [sessions,setSessions]=useState<Session[]>([]);
  const [current,setCurrent]=useState<Session|null>(null), [text,setText]=useState(''), [error,setError]=useState('');
  const [sending,setSending]=useState(false), [evidence,setEvidence]=useState<unknown>(null), [evidenceTitle,setEvidenceTitle]=useState('');
  const [opening,setOpening]=useState(''),[openError,setOpenError]=useState(''),[connectionLost,setConnectionLost]=useState(''),[controlling,setControlling]=useState('');
  const openVersion=useRef(0),evidenceVersion=useRef(0);
  const [evidenceOpen,setEvidenceOpen]=useState(false),[evidenceLoading,setEvidenceLoading]=useState(false),[evidenceError,setEvidenceError]=useState('');
  const evidenceRequest=useRef<{job:Job;item:Evidence}|null>(null);
  const [tick,setTick]=useState(Date.now()), [retry,setRetry]=useState(false);
  const [notice,setNotice]=useState(''),[showQuestions,setShowQuestions]=useState(false);
  const [showSources,setShowSources]=useState(false);
  const [direction,setDirection]=useState<number|null>(null),[pendingExample,setPendingExample]=useState('');
  const [deleting,setDeleting]=useState(''),deletingRef=useRef('');
  const sourceButton=useRef<HTMLButtonElement|null>(null);
  const evidenceFocus=useRef<HTMLElement|null>(null),drawer=useRef<HTMLElement|null>(null),input=useRef<HTMLTextAreaElement|null>(null);
  const hasTurns=!!current?.jobs?.length;
  const welcomePresent=usePresence(!hasTurns,reducedMotion,200),drawerPresent=usePresence(evidenceOpen,reducedMotion,220),directionPresent=usePresence(direction!==null,reducedMotion,180);
  const previousDirection=useRef<number|null>(null);if(direction!==null)previousDirection.current=direction;
  const shownDirection=direction??previousDirection.current;
  useAutoInput(input,text,!showSources&&!opening&&!openError,reducedMotion);
  const lastAnswer=current?.jobs?.filter(j=>['succeeded','partial'].includes(j.status)).at(-1);
  const relatedIndexes=lastAnswer?.evidence.some(e=>e.fact?.kind?.startsWith('prediction_'))?[1,4]:lastAnswer?.evidence.some(e=>e.kind==='claims')?[6,4]:lastAnswer?.evidence.some(e=>e.kind==='cluster_selections')?[3,4]:lastAnswer?.evidence.some(e=>e.kind==='rule_selections')?[4,2]:[0];
  const related=relatedIndexes.map(i=>health?.questions[i]).filter((q):q is string=>!!q&&!current?.jobs?.some(j=>j.text===q));
  const scrollTarget=useRef<string|null>(null);
  const selected=useRef(''), submitting=useRef(false), pending=useRef<{sid:string;text:string;idempotency_key:string}|null>(null);
  const running=current?.jobs?.find(active), unavailable=!!opening||!!openError||!!controlling||!!(current && (current.status!=='open'||deleting===current.id));
  const refreshHealth=()=>api<Health>('/health').then(setHealth);
  const refreshList=()=>api<Session[]>('/sessions').then(list=>{setSessions(list);return list;});
  async function open(id:string){
    const version=++openVersion.current,changing=selected.current!==id||!current;
    if(scrollTarget.current!==id)scrollTarget.current=null;
    selected.current=id;localStorage.setItem('selectedSession',id);setEvidence(null);setEvidenceOpen(false);evidenceVersion.current++;
    setOpenError('');if(changing){setOpening(id);setCurrent(null);setConnectionLost('');}
    try{
      const [session,h]=await Promise.all([api<Session>('/sessions/'+id),api<Health>('/health')]);
      if(version!==openVersion.current||selected.current!==id||deletingRef.current===id)return;
      setCurrent(session);setHealth(h);
    }catch(e){if(version===openVersion.current)setOpenError('暂时无法读取这段对话，请重试。');throw e;}
    finally{if(version===openVersion.current)setOpening('');}
  }
  useEffect(()=>{
    if(!scrollTarget.current||scrollTarget.current!==current?.id||!current.jobs?.length||welcomePresent||opening)return;
    scrollTarget.current=null;
    const frame=requestAnimationFrame(()=>document.querySelector('.turn:last-child')?.scrollIntoView({block:'start',behavior:reducedMotion?'auto':'smooth'}));
    return()=>cancelAnimationFrame(frame);
  },[current?.id,current?.jobs?.length,welcomePresent,opening,reducedMotion]);
  async function newSession(){
    if(sending||deletingRef.current)return;
    setSending(true);scrollTarget.current=null;
    setMenuOpen(false);setShowSources(false);setShowQuestions(false);setDirection(null);setPendingExample('');setText('');setNotice('');pending.current=null;setRetry(false);setError('');
    try {const s=await api<Session>('/sessions',{});await refreshList();await open(s.id);}
    catch(e){setError(String(e));}
    finally{setSending(false);}
  }
  async function deleteSession(s:Session){
    if(deletingRef.current||sending)return;
    if(!window.confirm(`确定删除“${s.title}”吗？\n对话、消息和数据依据将被删除，无法恢复。正在分析的任务会先停止。`))return;
    deletingRef.current=s.id;setDeleting(s.id);setError('');
    try{
      await api('/sessions/'+s.id+'/delete',{});
      setSessions(old=>old.filter(item=>item.id!==s.id));
      if(selected.current===s.id){selected.current='';openVersion.current++;evidenceVersion.current++;setEvidenceOpen(false);setOpenError('');setOpening('');localStorage.removeItem('selectedSession');setCurrent(null);setEvidence(null);setPendingExample('');setText('');pending.current=null;setRetry(false);}
      setNotice('对话已删除。');await refreshList();await refreshHealth();
      document.querySelector<HTMLButtonElement>('.new-button')?.focus();
    }catch(e){setError(String(e));}
    finally{deletingRef.current='';setDeleting('');}
  }
  useEffect(()=>{let disposed=false;
    (async()=>{try{await refreshHealth();const list=await refreshList();const id=localStorage.getItem('selectedSession');if(id&&!disposed){if(list.some(s=>s.id===id))await open(id);else localStorage.removeItem('selectedSession');}}catch(e){setError(String(e));}})();
    return()=>{disposed=true;};},[]);
  useEffect(()=>{
    if(!running||opening||deleting===running.session_id)return;
    let stopped=false, timer:ReturnType<typeof setTimeout>, seq=Math.max(0,...running.events.map(e=>e.seq));
    async function poll(){try{
      const j=await api<Job>('/jobs/'+running!.id+'?after_seq='+seq);
      if(stopped||deletingRef.current===j.session_id||selected.current!==j.session_id||j.id!==running!.id||j.turn_id!==running!.turn_id)return;
      if(!active(j)){
        const [s,h,list]=await Promise.all([api<Session>('/sessions/'+j.session_id),api<Health>('/health'),api<Session[]>('/sessions')]);
        if(stopped||deletingRef.current===s.id)return;
        setConnectionLost('');setHealth(h);setSessions(list);if(selected.current===s.id)setCurrent(s);
      }else{
        setConnectionLost('');setCurrent(s=>s?.id===j.session_id?{...s,jobs:s.jobs?.map(old=>old.id===j.id?(active(old)?{...j,events:mergeEvents(j,old.events,j.events)}:old):old)}:s);
        seq=Math.max(seq,...j.events.map(e=>e.seq));
        timer=setTimeout(poll,900);
      }
    }catch(e){if(!stopped&&deletingRef.current!==running!.session_id){setConnectionLost(running!.id);timer=setTimeout(poll,2500);}}}
    timer=setTimeout(poll,300);const clock=setInterval(()=>setTick(Date.now()),1000);
    return()=>{stopped=true;clearTimeout(timer);clearInterval(clock);};
  },[running?.id,deleting,opening]);
  useEffect(()=>{
    if(!running||running.execution_mode!=='request'||running.status==='cancelling'||cloudRuns.current.has(running.id))return;
    const job=running;cloudRuns.current.add(job.id);
    // Keep the execution request open; regular GET polling remains the source of truth.
    // This is never retried automatically after a network failure.
    void (async()=>{try{
      const response=await fetch('/api/jobs/'+job.id+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(!response.ok)throw new Error('execution request failed');
      const reader=response.body?.getReader();if(reader)while(!(await reader.read()).done){/* consume progress heartbeat */}
    }catch{if(selected.current===job.session_id)setError('分析连接中断，正在查询已保存的任务状态；不会自动重复调用模型。');}})();
  },[running?.id,running?.execution_mode,running?.status]);
  useEffect(()=>{if(current?.status!=='closing'||running||deleting===current.id)return;const id=current.id;let disposed=false;const timer=setInterval(()=>{api<Session>('/sessions/'+id).then(s=>{if(!disposed&&selected.current===id&&deletingRef.current!==id)setCurrent(s);}).catch(e=>{if(!disposed&&deletingRef.current!==id)setError(String(e));});},700);return()=>{disposed=true;clearInterval(timer);};},[current?.id,current?.status,running?.id,deleting]);
  async function submit(value=text){
    if(submitting.current||running||!value.trim()||unavailable||health?.budget.stopped)return;
    submitting.current=true;setSending(true);setError('');setNotice('');
    try{
      let sid=current?.id||(pending.current?.text===value?pending.current.sid:undefined);
      if(!sid){const s=await api<Session>('/sessions',{});sid=s.id;selected.current=sid;localStorage.setItem('selectedSession',sid);}
      if(!pending.current||pending.current.sid!==sid||pending.current.text!==value)pending.current={sid,text:value,idempotency_key:crypto.randomUUID()};
      const p=pending.current;
      await api<Job>('/sessions/'+sid+'/turns',{text:p.text,idempotency_key:p.idempotency_key});
      scrollTarget.current=sid;setText('');setPendingExample('');setShowQuestions(false);await open(sid);await refreshList();pending.current=null;setRetry(false);
    }catch(e){setError(String(e));setRetry(true);}
    finally{submitting.current=false;setSending(false);}
  }
  async function cancel(j:Job){
    setControlling(j.id);setError('');
    try{await api('/jobs/'+j.id+'/cancel',{});if(selected.current===j.session_id)await open(j.session_id);}
    catch(e){setError('停止请求未确认，请重试；当前任务状态会继续更新。');}
    finally{setControlling('');}
  }
  async function close(){if(!current)return;const sid=current.id;setControlling(sid);try{await api('/sessions/'+sid+'/close',{});if(selected.current===sid)await open(sid);await refreshList();}catch(e){setError(String(e));}finally{setControlling('');}}
  async function inspect(j:Job,e:Evidence){
    const version=++evidenceVersion.current;evidenceRequest.current={job:j,item:e};
    evidenceFocus.current=document.activeElement as HTMLElement;setEvidenceOpen(true);setEvidence(null);setEvidenceLoading(true);setEvidenceError('');setEvidenceTitle(e.label+'证据');
    try{const data=await api('/sessions/'+j.session_id+'/turns/'+j.turn_id+'/evidence/'+e.id);if(version===evidenceVersion.current&&selected.current===j.session_id)setEvidence(data);}
    catch(err){if(version===evidenceVersion.current)setEvidenceError('暂时无法读取这条依据，请重试。');}
    finally{if(version===evidenceVersion.current)setEvidenceLoading(false);}
  }
  function closeEvidence(){evidenceVersion.current++;setEvidenceOpen(false);evidenceFocus.current?.focus();}
  useEffect(()=>{if(!evidenceOpen)return;drawer.current?.querySelector('button')?.focus();
    const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();closeEvidence();}
      if(event.key==='Tab'){const nodes=drawer.current?.querySelectorAll<HTMLElement>('button,summary,[tabindex="0"],a[href]');if(!nodes?.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}};
    document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[evidenceOpen]);
  function useExample(question:string){setText(question);setPendingExample('');setNotice('已填入问题，你可以修改后再发送。');if(hasTurns)setShowQuestions(false);requestAnimationFrame(()=>{input.current?.focus();input.current?.scrollIntoView({block:'nearest'});});}
  function fill(question:string){if(text.trim()&&text!==question){setPendingExample(question);requestAnimationFrame(()=>document.querySelector('.replace-example')?.scrollIntoView({block:'nearest'}));return;}useExample(question);}
  async function exportAnalysis(j:Job,download:boolean){
    try{const sources=await Promise.all(j.evidence.map(async e=>({id:e.id,kind:e.label,data:await api('/sessions/'+j.session_id+'/turns/'+j.turn_id+'/evidence/'+e.id)})));
      const markdown=['# 玩家行为分析助手 · 单次分析','',`模拟数据演示 · ${health?.mode_label||''}`,`任务：${j.id}`,`问题：${j.text}`,'','## 核验回答','',j.answer?.answer_markdown||'','','引用已核验，不代表结论保证正确。','', j.answer?.limitations?.length?'## 未能完成的部分\n\n'+j.answer.limitations.join('\n\n'):'',methodMarkdown(j.evidence),'', '## 本轮公开证据','',...sources.map(s=>`### ${s.kind} · ${s.id}\n\n\u0060\u0060\u0060json\n${JSON.stringify(s.data,null,2)}\n\u0060\u0060\u0060`)].join('\n');
      if(download){const url=URL.createObjectURL(new Blob([markdown],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='分析-'+j.id.slice(0,8)+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice('已下载回答和数据来源，可用文本编辑器打开。');}
      else{await navigator.clipboard.writeText(markdown);setNotice('已复制回答和数据来源。');}
    }catch(e){setError(String(e));}}
  return <div className={"shell"+(menuOpen?" sidebar-open":"")}>
    {menuOpen&&<button className="sidebar-shade" aria-label="关闭导航" onClick={()=>setMenuOpen(false)}/>}
    <aside className="sidebar" id="sidebar"><div className="brand"><span className="brand-icon"><BrandMark/></span><span className="brand-name"><b>玩家洞察</b><small>让数据回答问题</small></span></div>
      <button className="new-button" disabled={!!deleting||sending} onClick={newSession}>＋ 新建对话</button>
      <div className="section-label">对话记录 <span>{sessions.length.toString().padStart(2,'0')}</span></div>
      <nav aria-label="历史对话">{sessions.length===0?<p className="muted">从第一个问题开始，分析记录会出现在这里。</p>:sessions.map(s=><div className="history-row" key={s.id} data-session-id={s.id}><button disabled={!!deleting||sending} className={'history '+(current?.id===s.id?'selected':'')} onClick={()=>{setMenuOpen(false);setShowSources(false);open(s.id).catch(e=>setError(String(e)));}}><span>{s.title}</span><small>{deleting===s.id?'正在删除…':`${new Date(s.created*1000).toLocaleDateString('zh-CN')} · ${s.status==='open'?'对话中':'只读记录'}`}</small></button><button className="history-delete" aria-label={'删除对话：'+s.title} title="删除对话" disabled={!!deleting||sending} onClick={()=>deleteSession(s)}><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg></button></div>)}</nav>
      <div className="sidebar-footer" role="status"><span className="service-indicator" data-state={health?'connected':error?'failed':'connecting'}/>{health?.mode==='live'?'模型 · DeepSeek':health?'本地模式':error?'服务连接失败':'正在连接服务'}<small>玩家行为分析助手</small></div>
    </aside>
    <main inert={menuOpen}><header className="workspace-header"><div className="header-title"><button className="menu-toggle" aria-label="展开导航" aria-expanded={menuOpen} aria-controls="sidebar" onClick={()=>setMenuOpen(v=>!v)}>☰</button><h1>{showSources?'数据源':hasTurns?current?.title:'分析工作台'}</h1></div><div className="header-actions"><button className="source-trigger" ref={sourceButton} onClick={()=>setShowSources(v=>!v)}>{showSources?'返回分析':'管理数据源'}</button><UsageDetails key={current?.id||'new'} usage={sumUsage(current?.jobs?.map(j=>j.usage)||[])} scope="本对话" running={!!running} stale={!!connectionLost}/></div></header>
      <div className="data-context"><span className="data-context-icon" aria-hidden="true">▤</span><span>玩家行为数据</span><span className="data-tag">模拟数据</span></div>
      <div hidden={!showSources}><DataSource active={showSources} onBack={()=>{setShowSources(false);sourceButton.current?.focus();}}/></div>
      {!showSources&&(opening||openError)&&<div className="view-feedback" role="status">{opening?'正在读取对话…':<>{openError}<button onClick={()=>open(selected.current).catch(()=>{})}>重新读取对话</button></>}</div>}
      <div className={'analysis-workspace '+(hasTurns?'conversation-mode':'start-mode')} hidden={showSources||!!opening||!!openError}>
      {welcomePresent&&<section className={"start-intro "+(hasTurns?"is-exiting":"welcome")} aria-hidden={hasTurns||undefined}><div className="intro-copy"><span className="eyebrow">玩家洞察</span><h2>想了解玩家的哪些行为？</h2><p>输入你的问题，让数据帮你找到答案。</p></div></section>}
      {hasTurns&&<div className="conversation-heading"><span>本次对话 · {current?.jobs?.length} 个问题</span><button className="more-questions" aria-expanded={showQuestions} aria-controls="question-picker" disabled={!!running||sending||!!unavailable} onClick={()=>setShowQuestions(v=>!v)}>{showQuestions?'收起分析方向':'换个分析方向'}</button></div>}
      <section id="question-picker" className="question-picker" aria-label="分析方向" hidden={hasTurns&&!showQuestions}>
        <div className="picker-heading"><h2>分析方向</h2><span>不必先选，直接提问也可以</span></div>
        <div className="direction-options" role="group" aria-label="选择分析方向"><DirectionSelection selected={direction} count={health?.capabilities.length||0}/>{health?.capabilities.map((c,i)=><button key={c.title} aria-pressed={direction===i} aria-controls="direction-details" disabled={!!running||sending||!!unavailable} onClick={()=>setDirection(direction===i?null:i)}>{c.title}</button>)}</div>
        {directionPresent&&shownDirection!==null&&health?.capabilities[shownDirection]&&<div key={shownDirection} className={"direction-details"+(direction===null?" is-exiting":"")} id="direction-details" aria-hidden={direction===null||undefined} inert={direction===null}><h3>{health.capabilities[shownDirection!].title}</h3><p>{health.capabilities[shownDirection!].description}</p><div className="direction-examples"><span>可以这样问</span>{health.capabilities[shownDirection!].examples.map(q=><button key={q} aria-label={q} disabled={!!running||sending||!!unavailable} onClick={()=>fill(q)}>{q}<span aria-hidden="true"> ↗</span></button>)}</div></div>}
        <p className="picker-note">直接提问，也可以选择一个方向寻找灵感。</p>
      </section>
      <section className="conversation" aria-label="分析对话">
        {current?.jobs?.map(j=><article className="turn" key={j.id}><div className="user-message"><span className="avatar">你</span><div>{j.text}</div></div>
          <div className="assistant-message"><span className="avatar agent"><BrandMark/></span><div className="answer"><div className={'status '+(['succeeded','partial'].includes(j.status)?'verified':'')}><span>{labels[j.status]||j.status}</span><small>{Math.max(0,Math.floor(((active(j)?tick/1000:j.updated)-j.created)))} 秒</small></div>
            <Execution events={j.events} status={j.status} disconnected={connectionLost===j.id}/>
            {j.answer?.status==='control'&&<div className="scope-reply" role="status"><p>{j.answer.message}</p>{j.routing&&['guidance','clarification','out_of_scope'].includes(j.routing.kind)&&<small>这条提示未调用大模型，你可以继续提问。</small>}<div className="scope-options">{j.answer.choices?.map(c=><button key={c.text} disabled={!!running||sending||!!unavailable||current.jobs?.at(-1)?.id!==j.id} onClick={()=>fill(c.text)}>{c.text}</button>)}<button disabled={!!running||sending||!!unavailable} onClick={()=>fill(j.text)}>修改这个问题</button></div></div>}
            {j.answer&&['succeeded','partial'].includes(j.status)?<div className="result-reveal">{j.answer.limitations?.length?<aside className="partial-notice" aria-label="未能完成的部分"><strong>这次能回答的部分</strong>{j.answer.limitations.map(t=><p key={t}>{t}</p>)}</aside>:null}<div className="answer-toolbar"><h3>分析结果</h3><button onClick={()=>exportAnalysis(j,false)}>复制回答</button><button onClick={()=>exportAnalysis(j,true)}>下载分析</button></div>{j.evidence.some(e=>e.kind!=='knowledge_selections')?<><ResultOverview evidence={j.evidence} onInspect={e=>inspect(j,e)}/><AnalysisMethods evidence={j.evidence} onInspect={e=>inspect(j,e)}/><details className="detailed-data"><summary>查看详细数据</summary><Results evidence={j.evidence} onInspect={e=>inspect(j,e)}/></details><details className="verified-text"><summary>查看完整回答与统计范围</summary><SafeMarkdown text={j.answer.answer_markdown}/></details></>:<><KnowledgeAnswer job={j}/><AnalysisMethods evidence={j.evidence} onInspect={e=>inspect(j,e)}/></>}<details className="source-list"><summary>查看全部数据来源（{j.evidence.length}）</summary><div className="evidence-links">{j.evidence.map((e,i)=><button key={e.id} onClick={()=>inspect(j,e)}>↗ {e.label}证据 {i+1}</button>)}</div></details>{j.evidence.length===0&&<p className="muted">这是对结果使用方式的说明，没有新增统计数据。</p>}<small className="muted">数据源：模拟玩家行为数据。</small></div>:j.error?<div role="status" className="failure"><p>{j.error.message}</p>{j.error.code==='offline_unsupported'&&<button disabled={!!running||sending||!!unavailable} onClick={()=>fill(j.text)}>修改这个问题</button>}<details><summary>查看问题详情</summary><code>任务 {j.id} · {j.error.code}</code></details><button onClick={()=>navigator.clipboard.writeText(JSON.stringify({job_id:j.id,...j.error}))}>复制错误摘要</button></div>:null}
            {active(j)&&<button className="cancel" disabled={j.status==='cancelling'||controlling===j.id} onClick={()=>cancel(j)}>{controlling===j.id?'正在发送停止请求…':j.status==='cancelling'?'正在取消…':'取消任务'}</button>}
            <UsageDetails usage={j.usage} running={active(j)} stale={connectionLost===j.id}/>
          </div></div></article>)}
      </section>
      <footer className="composer-area"><label className="composer-heading" htmlFor="question">{hasTurns?'接着问一个问题':'你的问题'}</label>{error&&<div role="alert" className="error-banner">{error}{retry&&pending.current&&<button disabled={sending} onClick={()=>submit(pending.current!.text)}>重试同一提交</button>}</div>}
        {sending&&<p className="operation-pending" role="status">正在提交，请稍候…</p>}
        {notice&&<p className="notice" role="status">{notice}</p>}
        {pendingExample&&<div className="replace-example" role="status"><p>输入框里已有内容。要换成下面这个问题吗？</p><blockquote>{pendingExample}</blockquote><button onClick={()=>useExample(pendingExample)}>替换输入内容</button><button onClick={()=>{setPendingExample('');input.current?.focus();}}>保留我的问题</button></div>}
        {health?.budget.stopped&&<p className="error-banner">分析服务已暂停，请联系管理员检查模型连接和调用记录。已完成的分析仍可查看。</p>}
        {current&&(current.status!=='open'||deleting===current.id)&&<p className="readonly">{deleting===current?.id?'正在停止任务并删除对话，请稍候…':current?.status==='close_failed'?'对话暂时未能结束，请再次点击“结束对话”重试。':'此对话已结束或为历史只读记录。请新建对话继续。'}</p>}
        {lastAnswer&&!unavailable&&related.length>0&&<div className="related-questions" aria-label="接着了解"><span>接着了解</span>{related.map(q=><button className="followup" key={q} aria-label={q} disabled={!!running||sending} onClick={()=>fill(q)}>{q} ↗</button>)}</div>}
        <form onSubmit={e=>{e.preventDefault();submit();}}><label className="sr-only" htmlFor="question">输入问题</label><textarea ref={input} id="question" placeholder={hasTurns?'继续输入你想了解的问题…':'写下你想了解的玩家行为…'} value={text} maxLength={4000} disabled={!!running||sending||!!unavailable} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing&&e.nativeEvent.keyCode!==229){e.preventDefault();submit();}}}/><button className="send" aria-label="发送问题" type="submit" disabled={!text.trim()||!!running||sending||!!unavailable||health?.budget.stopped}><span>{hasTurns?'发送':'开始分析'}</span><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 16V4m-5 5 5-5 5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg></button></form>
        <div className="composer-meta"><span>Enter 发送 · Shift + Enter 换行</span>{current&&hasTurns&&<button onClick={close} disabled={current.status==='closed'||current.status==='read_only'}>结束对话</button>}<span>{running?'正在分析，完成后可继续提问':'分析结论请结合数据范围使用'}</span></div>
        
      </footer>
      </div>
    </main>
    {drawerPresent&&<><div className={"drawer-shade"+(!evidenceOpen?" is-exiting":"")} onClick={closeEvidence}/><aside ref={drawer} role="dialog" aria-modal={evidenceOpen||undefined} aria-hidden={!evidenceOpen||undefined} inert={!evidenceOpen} className={"evidence-drawer"+(!evidenceOpen?" is-exiting":"")} aria-label="证据详情"><div className="drawer-heading"><div><span className="eyebrow">数据从哪里来</span><h2>{evidenceTitle}</h2></div><button aria-label="关闭证据" onClick={closeEvidence}>×</button></div><p>这里保存了生成这条回答时使用的数据。即使继续追问，你仍能查看当时的依据。</p>{evidenceLoading?<p className="drawer-feedback" role="status">正在读取这条依据…</p>:evidenceError?<div className="drawer-feedback" role="alert">{evidenceError}<button onClick={()=>{const r=evidenceRequest.current;if(r)inspect(r.job,r.item);}}>重新读取依据</button></div>:evidence!==null?<EvidenceView data={evidence as Record<string,unknown>}/>:null}</aside></>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
