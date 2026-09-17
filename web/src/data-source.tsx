import {useEffect,useRef,useState} from 'react';
import type {Sheet} from './source-worker';

type Mapping=Record<string,string>;
type Preview={file:File;key:string;sheets:Sheet[];sheet:number;header:boolean;encoding:string;mapping:Mapping;saved:boolean};
const fields=[['player_id','玩家编号','用来区分不同玩家'],['event_time','发生时间','行为发生的日期或时间'],['event_name','玩法或行为名称','例如地图探索、开始剧情'],['version_id','游戏版本','用于区分不同次游戏更新'],['story_id','剧情编号','区分不同剧情'],['duration_minutes','游玩时长（分钟）','如果原数据不是分钟，接入时需转换']];
function parse(file:File,encoding:string){
  return new Promise<Sheet[]>((resolve,reject)=>{
    const worker=new Worker(new URL('./source-worker.ts',import.meta.url),{type:'module'});
    const timer=setTimeout(()=>{worker.terminate();reject(new Error('读取超时，请拆分文件后再试。'));},20000);
    worker.onmessage=e=>{clearTimeout(timer);worker.terminate();e.data.error?reject(new Error(e.data.error)):resolve(e.data.sheets);};
    worker.onerror=()=>{clearTimeout(timer);worker.terminate();reject(new Error('无法读取文件，请检查格式后重试。'));};
    worker.postMessage({file,encoding});
  });
}
function columns(p:Preview){
  const rows=p.sheets[p.sheet]?.rows||[],width=Math.max(0,...rows.map(r=>r.length));
  return Array.from({length:width},(_,i)=>({key:String(i),label:p.header?(rows[0]?.[i]?.trim()||`未命名列 ${i+1}`):`第 ${i+1} 列`}));
}
function fingerprint(file:File){return file.arrayBuffer().then(buffer=>crypto.subtle.digest('SHA-256',buffer)).then(hash=>Array.from(new Uint8Array(hash),n=>n.toString(16).padStart(2,'0')).join(''));}
const storageKey=(p:Preview)=>`data-mapping-v1:${p.key}:${p.sheet}:${p.header}:${p.encoding}`;
function restore(p:Preview):Preview{try{const raw=JSON.parse(localStorage.getItem(storageKey(p))||'null');const keys=columns(p).map(c=>c.key);if(raw&&typeof raw==='object'&&fields.every(([f])=>!raw[f]||keys.includes(raw[f])))return {...p,mapping:raw,saved:true};}catch{/* A corrupt or unavailable local store does not prevent preview. */}return {...p,mapping:{},saved:false};}
export function DataSource({onBack,active}:{onBack:()=>void;active:boolean}){
  const [items,setItems]=useState<Preview[]>([]),[selected,setSelected]=useState(0),[busy,setBusy]=useState(false),[errors,setErrors]=useState<string[]>([]),[notice,setNotice]=useState('');
  const [inputEncoding,setInputEncoding]=useState('utf-8');
  const fileInput=useRef<HTMLInputElement>(null),folderInput=useRef<HTMLInputElement>(null),heading=useRef<HTMLHeadingElement>(null),alive=useRef(true),lock=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{if(active)heading.current?.focus();},[active]);
  const p=items[selected],cols=p?columns(p):[],rows=p?.sheets[p.sheet]?.rows.slice(p.header?1:0)||[];
  const selectedFields=Object.values(p?.mapping||{}).filter(v=>v!=='');
  const duplicate=new Set(selectedFields).size!==selectedFields.length;
  const irregular=p?rows.filter(r=>r.length!==cols.length).length:0;
  const update=(change:Partial<Preview>)=>setItems(old=>old.map((v,i)=>i===selected?{...v,...change}:v));
  async function choose(files:FileList|null){
    if(!files?.length||lock.current)return;lock.current=true;setBusy(true);setNotice('');const problems:string[]=[],next:Preview[]=[];
    const accepted=Array.from(files).filter(f=>/\.(csv|xlsx)$/i.test(f.name));
    if(accepted.length!==files.length)problems.push('已跳过不支持的文件；支持 CSV 和 Excel .xlsx，旧版 .xls 请先另存为 .xlsx。');
    if(accepted.length>10||accepted.reduce((n,f)=>n+f.size,0)>20*1024*1024)problems.push('一次最多选择 10 个表格文件，总大小不超过 20 MB。请减少选择后重试。');
    else for(const file of accepted){try{
      if(file.size>5*1024*1024)throw new Error('单个文件不能超过 5 MB。');
      const sheets=await parse(file,inputEncoding);if(!sheets.length)throw new Error('工作簿中没有工作表。');
      next.push(restore({file,key:await fingerprint(file),sheets,sheet:0,header:true,encoding:inputEncoding,mapping:{},saved:false}));
    }catch(e){problems.push(file.name+'：'+(e instanceof Error?e.message:'读取失败'));}}
    if(alive.current){if(next.length){setItems(next);setSelected(0);}setErrors(problems);setBusy(false);}lock.current=false;
  }
  async function encoding(value:string){if(!p||lock.current)return;lock.current=true;setBusy(true);try{const sheets=await parse(p.file,value);update(restore({...p,sheets,encoding:value}));setErrors([]);}catch(e){setErrors([String(e)]);}finally{setBusy(false);lock.current=false;}}
  function save(){if(!p||duplicate||!selectedFields.length)return;try{localStorage.setItem(storageKey(p),JSON.stringify(p.mapping));update({saved:true});setNotice('字段配置已保存。重新选择同一文件即可恢复；当前分析仍使用模拟数据。');}catch{setErrors(['浏览器未能保存配置，请使用“下载字段配置”保存到文件。']);}}
  function download(){if(!p)return;const url=URL.createObjectURL(new Blob([JSON.stringify({format:'player-insights-mapping-v1',status:'draft_not_connected',file_name:p.file.name,sha256:p.key,sheet:p.sheets[p.sheet].name,first_row_is_header:p.header,encoding:p.encoding,columns:cols,mapping:p.mapping},null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=p.file.name+'.字段配置.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  return <section className="source-panel" aria-label="数据源管理">
    <div className="source-heading"><div><span className="eyebrow">先认识你的数据</span><h2 tabIndex={-1} ref={heading}>数据源</h2></div><button onClick={onBack}>返回分析</button></div>
    <p className="source-description">用示例数据体验，也可以选择自己的表格，先看看内容，再告诉助手每一列是什么。</p>
    <div className="active-source"><svg viewBox="0 0 28 28" fill="none" aria-hidden="true"><ellipse cx="14" cy="6" rx="10" ry="4" stroke="currentColor" strokeWidth="1.7"/><path d="M4 6v8c0 5 20 5 20 0V6M4 14v8c0 5 20 5 20 0v-8" stroke="currentColor" strokeWidth="1.7"/></svg><div><h3>玩家行为示例数据</h3><p>版本对比、参与预测、玩家分组与玩法关联 · 模拟数据</p></div><span className="source-pill">分析中使用</span></div>
    <div className="upload-box"><h3>预览你自己的数据</h3><p>选择 CSV、Excel（.xlsx），或包含这些表格的文件夹。</p><div className="source-actions"><button className="primary" disabled={busy} onClick={()=>fileInput.current?.click()}>选择文件</button><button disabled={busy} onClick={()=>folderInput.current?.click()}>选择文件夹</button></div><input className="sr-only" tabIndex={-1} aria-label="选择数据文件" ref={fileInput} type="file" multiple accept=".csv,.xlsx" onChange={e=>{choose(e.target.files);e.target.value='';}}/><input className="sr-only" tabIndex={-1} aria-label="选择数据文件夹" ref={folderInput} type="file" multiple {...{webkitdirectory:''}} onChange={e=>{choose(e.target.files);e.target.value='';}}/><p>单个文件 ≤ 5 MB · 一次最多 10 个文件、共 20 MB</p></div>
    <div className="source-options"><label>CSV 文件编码<select aria-label="读取 CSV 的编码" value={inputEncoding} disabled={busy} onChange={e=>setInputEncoding(e.target.value)}><option value="utf-8">UTF-8（推荐）</option><option value="gb18030">GB18030（常见中文编码）</option></select></label><span>如果中文无法显示，请换一种编码后重新选择文件。</span></div>
    <p className="source-note">文件只在你的浏览器中读取，不会上传。此处用于预览和保存字段配置；要用于现有分析，还需适配统计规则与模型。当前分析继续使用上方模拟数据。</p>
    {busy&&<p className="notice" role="status">正在读取表格，请稍候…</p>}
    {!!errors.length&&<div className="import-notices" role="alert">{errors.map((e,i)=><div key={i}>{e}</div>)}{errors.some(e=>e.includes('编码'))&&<p>请先在 Excel 中另存为“CSV UTF-8”，再重新选择。</p>}</div>}
    {!!items.length&&<><div className="source-file-tabs" role="tablist" aria-label="已选择文件">{items.map((v,i)=><button role="tab" key={v.key+i} aria-selected={i===selected} disabled={busy} onClick={()=>{setSelected(i);setNotice('');}}>{v.file.webkitRelativePath||v.file.name}</button>)}</div>
    <div className="source-options"><label>工作表<select aria-label="工作表" disabled={busy} value={p.sheet} onChange={e=>update(restore({...p,sheet:Number(e.target.value)}))}>{p.sheets.map((s,i)=><option key={i} value={i}>{s.name}</option>)}</select></label><label><input type="checkbox" checked={p.header} disabled={busy} onChange={e=>update(restore({...p,header:e.target.checked}))}/>第一行是列名</label>{p.file.name.toLowerCase().endsWith('.csv')&&<label>编码<select value={p.encoding} disabled={busy} onChange={e=>encoding(e.target.value)}><option value="utf-8">UTF-8</option><option value="gb18030">GB18030（简体中文）</option></select></label>}</div>
    <div className="preview-heading"><h3>表格预览</h3><small>{rows.length.toLocaleString()} 行 · {cols.length} 列 · 显示前 8 行</small></div>
    {rows.length?<div className="table-scroll" tabIndex={0} aria-label="导入数据预览"><table><thead><tr>{cols.map((c,i)=><th key={i}>{c.label}<small> · {i+1}</small></th>)}</tr></thead><tbody>{rows.slice(0,8).map((r,i)=><tr key={i}>{cols.map((c,j)=><td key={c.key}>{r[j]||'—'}</td>)}</tr>)}</tbody></table></div>:<p className="preview-empty">这张表还没有数据，请选择其他工作表，或取消“第一行是列名”。</p>}
    {!!irregular&&<p className="mapping-errors">有 {irregular} 行的列数与表格宽度不一致，请检查缺失单元格或分隔符。</p>}
    {cols.length>0&&<><div className="preview-heading"><h3>告诉助手，每一列是什么</h3><small>按需选择，不存在的字段可以留空</small></div><div className="mapping-grid">{fields.map(([key,label,help])=><label key={key}><span>{label} <small>· {help}</small></span><select aria-label={label} value={p.mapping[key]??''} disabled={busy} onChange={e=>{update({mapping:{...p.mapping,[key]:e.target.value},saved:false});setNotice('');}}><option value="">暂不对应</option>{cols.map(c=><option key={c.key} value={c.key}>{c.label}（第 {Number(c.key)+1} 列）</option>)}</select></label>)}</div>
    {duplicate&&<p className="mapping-errors" role="alert">同一列不能同时对应多个字段，请调整后保存。</p>}
    <div className="source-bottom"><div className="source-actions"><button className="primary" disabled={busy||duplicate||!selectedFields.length} onClick={save}>保存字段配置</button><button disabled={busy||duplicate||!selectedFields.length} onClick={download}>下载字段配置</button><button disabled={busy} onClick={()=>{localStorage.removeItem(storageKey(p));update({mapping:{},saved:false});setNotice('');}}>清空字段配置</button></div><p>{p.saved?'配置已保存 · 待接入分析':'尚未保存 · 不会更换当前分析数据'}</p></div></>}
    {notice&&<p className="source-success" role="status">{notice}</p>}</>}
  </section>;
}
