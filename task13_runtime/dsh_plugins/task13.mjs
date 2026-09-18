// Fixed-release Cordis extension. Plain ESM; uses only bundled Node built-ins.
// DSH owns the agent loop. This extension registers ten MCP delegates and guards.
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { createHash, randomUUID } from 'node:crypto';

export const name = 'task13-registered-analysis';
export const inject = ['tools', 'llm', 'agents', 'systemPrompt'];
const names = ['inspect_context','check_quality','query_metric','compare_results','predict_registered','read_model_card','get_evidence','search_knowledge','assign_segments','query_association_rules'];
const stable = value => JSON.stringify(value, function(k,v) {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? Object.fromEntries(Object.keys(v).sort().map(key=>[key,v[key]])) : v;
});

export async function apply(ctx) {
  const cfg = JSON.parse(fs.readFileSync(process.env.TASK13_BRIDGE_CONFIG, 'utf8'));
  const secret = process.env.DEEPSEEK_API_KEY;
  // Fixed release interpolates templates strictly, but does not rescan a variable
  // value. Keep the answer's literal {{claim:...}} syntax in that value.
  ctx.systemPrompt.variable('task13_public_instructions',()=>process.env.DSH_SYSTEM_PROMPT);
  const scrub = value => {
    const text = JSON.stringify(value, (key,v) => /authorization|api.?key|access.?token|secret/i.test(key) ? '[REDACTED]' : v);
    return secret ? text.split(secret).join('[REDACTED]') : text;
  };
  const log = (file, value) => {
    const debug=['dsh_stream.jsonl','tools.jsonl'];
    if(debug.includes(file) && process.env.APP_DEBUG!=='1') return;
    const path=cfg.directory+'/'+file;
    if(debug.includes(file) && fs.existsSync(path) && fs.statSync(path).size>=8388608) return;
    fs.appendFileSync(path,scrub({at:new Date().toISOString(),...value})+'\n');
  };
  const phase = value => log('phase.jsonl',{phase:value});
  phase('DSH插件加载，等待真实MCP握手及工具发现');
  const fail = (code, message) => { const e = new Error(message); e.code=code; throw e; };
  const safeEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    /^(SYSTEMROOT|WINDIR|COMSPEC|PATH|PATHEXT|TEMP|TMP|USERPROFILE|APPDATA|LOCALAPPDATA|PROGRAMFILES|PROGRAMFILES\(X86\)|OS|APP_ASSET_DIR|APP_STATE_DIR|APP_DEBUG|APP_READ_AUDIT)$/i.test(key)));
  Object.assign(safeEnv,{PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8',PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'});
  let closed=false, blocked=false, turnBlocked=false, currentTurn=null, toolCount=0, contextReady=false, contextEvidenceId=null;
  let discoveryRequired=false, discoveryReady=false, discoveryEvidenceId=null, contextAttempts=0, repairRequestUsed=false;
  const pending = new Map();
  const toolAdmissions = new Map();
  let taskToolCount=0;
  const child = spawn(cfg.original_python, ['-m','task13_runtime.bridge','--config',process.env.TASK13_BRIDGE_CONFIG],
    {cwd:cfg.project_root,env:safeEnv,stdio:['pipe','pipe','pipe'],windowsHide:true,shell:false});
  child.stderr.on('data', data=>process.stderr.write(data));
  log('plugin.jsonl',{event:'bridge_spawned',dsh_pid:process.pid,bridge_pid:child.pid,credential_present_in_bridge_env:false});
  const invalidate = reason => {
    blocked=true;
    for (const entry of pending.values()) {clearTimeout(entry.timer);entry.reject(new Error(reason));}
    pending.clear();
  };
  child.on('exit',(code,signal)=>{closed=true;invalidate('bridge exited');log('plugin.jsonl',{event:'bridge_exit',code,signal});});
  child.on('error', error=>invalidate(error.message));
  const readline = createInterface({input:child.stdout});
  readline.on('line', line=>{
    try {
      const message=JSON.parse(line), entry=pending.get(message.id);
      if (!entry || entry.op!==message.op) fail('CALL_ID','unknown, duplicate or crossed internal reply');
      pending.delete(message.id);clearTimeout(entry.timer);
      if (message.error) {
        if (message.error.code==='tool_timeout') blocked=true;
        const e=new Error(message.error.message);e.code=message.error.code;entry.reject(e);
      }
      else entry.resolve(message.result);
    } catch(error) {log('plugin.jsonl',{event:'internal_reply_rejected',code:error.code||null,message:error.message});invalidate(error.message);child.kill();}
  });
  const rpc=(op,args={},signal=null)=>new Promise((resolve,reject)=>{
    if (closed || blocked) return reject(new Error('bridge closed or run stopped'));
    const id=randomUUID();
    const timer=setTimeout(()=>{invalidate('bridge/tool deadline exceeded');child.kill();},600000);
    pending.set(id,{op,resolve,reject,timer});
    if (signal) signal.addEventListener('abort',()=>{invalidate('caller cancelled');child.kill();},{once:true});
    child.stdin.write(JSON.stringify({id,op,args})+'\n');
  });
  const turn=()=>{
    const value=JSON.parse(fs.readFileSync(cfg.turn_file,'utf8'));
    if (value.stopped) fail('STOPPED','controller stopped turn');
    if (value.turn_id!==currentTurn) {
      currentTurn=value.turn_id;toolCount=0;contextReady=false;contextEvidenceId=null;turnBlocked=false;
      contextAttempts=0;
      repairRequestUsed=false;
      discoveryRequired=value.require_rule_discovery===true;discoveryReady=false;discoveryEvidenceId=null;
    }
    return value;
  };
  const originalFetch=globalThis.fetch;
  let catalogue=null;
  const ensureTools = tools => {
    const functions=(tools||[]).map(t=>t.type==='function'?t.function:t);
    const wanted=catalogue.map(t=>({name:t.name,description:t.description,parameters:t.input_schema}));
    if (stable([...functions].sort((a,b)=>a.name.localeCompare(b.name)))!==stable([...wanted].sort((a,b)=>a.name.localeCompare(b.name))))
      fail('CATALOG','model function schemas differ from actual tools/list');
  };
  // Intercept the adapter's actual fetch, not merely a post-hoc session event.
  // No redirects, telemetry endpoints, model lists or auxiliary HTTP are permitted.
  globalThis.fetch=async (input,init={})=>{
    let reserved=null, requestStarted=null;
    try {
      turn();
      for (const admission of toolAdmissions.values()) {
        if (admission.turn!==currentTurn || !admission.promise) continue;
        const outcome=await admission.promise;
        if (outcome.error) throw outcome.error;
      }
      if (blocked || turnBlocked) fail('STOPPED','network disabled for run or current turn');
      if (turn().answer_repair) {
        if (repairRequestUsed) fail('model_limit','Only one answer correction HTTP request is permitted');
        repairRequestUsed=true;
      }
      const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
      const allowed=cfg.mode==='live'?'https://api.deepseek.com/chat/completions':cfg.offline_base_url+'/chat/completions';
      if (url!==allowed || (init.method||'GET').toUpperCase()!=='POST') fail('NETWORK_DENIED','unregistered external endpoint or method');
      if (cfg.mode!=='live' && !/^http:\/\/127\.0\.0\.1:\d+\/chat\/completions$/.test(url)) fail('NETWORK_DENIED','offline endpoint is not loopback');
      if (typeof init.body!=='string') fail('BODY','only serialized text JSON requests are supported');
      const body=JSON.parse(init.body);
      if (body.model!=='deepseek-flash' || body.temperature!==0 || body.max_tokens!==4096 || body.thinking?.type!=='disabled' || body.stream!==true)
        fail('REQUEST_CONFIG','wire model/thinking/temperature/output/stream contract differs');
      ensureTools(body.tools);
      if (body.messages.some(m=>Array.isArray(m.content)&&m.content.some(b=>b.type!=='text')))
        fail('ATTACHMENT','only text model messages are authorized');
      // Fixed DSH 0.1.5rc1 does not serialize response_format. Use the official
      // Chat Completions wire field here, retaining native tools and messages.
      if (body.response_format!==undefined && stable(body.response_format)!==stable({type:'json_object'}))
        fail('REQUEST_CONFIG','response_format conflicts with the fixed JSON output contract');
      body.response_format={type:'json_object'};
      // Host-fixed first step, including note-only follow-ups. Keep the entire
      // native catalogue; DSH/model still construct and dispatch the tool call.
      // Only a successful MCP return in this turn releases the constraint.
      const requiredTool=!contextReady?'inspect_context':discoveryRequired&&!discoveryReady?'query_association_rules':null;
      body.tool_choice=turn().answer_repair?'none':requiredTool?{type:'function',function:{name:requiredTool}}:'auto';
      // This host requirement contains no answer, rule ID or test identifier.
      // Parameters are still produced by the model, and DSH dispatches real MCP.
      if (discoveryRequired) {
        const guidance='宿主本轮开发排名前置约束：'+(discoveryReady
          ? '本轮已取得有效discovery_V1_V3证据，可继续查询目标分区并回答。'
          : '本轮尚未取得有效discovery_V1_V3证据。取得inspect_context后，调用query_association_rules，evaluation_id=discovery_V1_V3，rule_set_id使用实际工具目录允许值。上轮查过也必须本轮重查；不得直接结束。')+
        '开发查询用于确认冻结排名，不要求在答案中展示开发期数字。目标分区读数仍须本轮实际查询；工具失败不能视为成功。';
        const system=body.messages.find(message=>message.role==='system');
        if (typeof system?.content==='string') system.content+='\n\n'+guidance;
        else if (Array.isArray(system?.content)) system.content.push({type:'text',text:guidance});
        else fail('REQUEST_CONFIG','system message missing for current-turn prerequisite');
      }
      const contextGate={turn_id:currentTurn,context_ready:contextReady,evidence_id:contextEvidenceId,
        policy:'host_fixed_current_turn_context_first'};
      const discoveryGate={turn_id:currentTurn,required:discoveryRequired,ready:discoveryReady,
        evidence_id:discoveryEvidenceId,policy:'host_fixed_current_turn_development_lookup'};
      if (cfg.condition==='H1') {
        const summary=await rpc('summary');
        if (Buffer.byteLength(summary.text,'utf8')>8192) fail('SUMMARY','public summary exceeds 8 KiB');
        body.messages.push({role:'system',content:summary.text});
      } else if (cfg.condition!=='H0') fail('CONDITION','unknown frozen condition');
      const requestBody=JSON.stringify(body);
      const bytes=Buffer.byteLength(requestBody,'utf8');
      const bodyHash=createHash('sha256').update(requestBody,'utf8').digest('hex');
      // Let fetch calculate Content-Length for the final body, not the DSH input.
      const headers=new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
      headers.delete('content-length');
      if (headers.get('authorization')!=='Bearer '+secret)
        fail('CREDENTIAL','outgoing credential does not match explicitly supplied process credential');
      reserved=await rpc('reserve',{request_bytes:bytes,max_tokens:body.max_tokens,request_body_sha256:bodyHash});
      phase('等待模型HTTP/SSE响应');
      log('http.jsonl',{event:'attempt',attempt_id:reserved.attempt_id,turn_id:currentTurn,url,request:body,
        request_bytes:bytes,request_body_sha256:bodyHash,context_gate:contextGate,discovery_gate:discoveryGate,stream:true});
      const signal=AbortSignal.any([...(init.signal?[init.signal]:[]),AbortSignal.timeout(cfg.model_timeout_seconds*1000)]);
      requestStarted=performance.now();
      const response=await originalFetch(input,{...init,body:requestBody,headers,signal,redirect:'error'});
      // Buffer a single bounded-output SSE response for lossless wire audit.
      // DSH's own adapter still parses the original SSE and assembles tool fragments.
      const raw=await response.text();
      let usage=null, fingerprint=null, returnedModel=null, responseId=null, done=false;
      for (const line of raw.split(/\r?\n/)) {
        if (!line.startsWith('data:')) continue;
        const data=line.slice(5).trim();
        if (data==='[DONE]') {done=true;continue;}
        const chunk=JSON.parse(data);
        if (chunk.usage) usage=chunk.usage; // final cumulative usage, never sum cumulative chunks
        if (chunk.system_fingerprint!==undefined) fingerprint=chunk.system_fingerprint;
        if (chunk.model!==undefined) returnedModel=chunk.model;
        if (chunk.id!==undefined) responseId=chunk.id;
      }
      log('http.jsonl',{event:'response',attempt_id:reserved.attempt_id,status:response.status,
        provider_request_id:response.headers.get('x-request-id'),response_id:responseId,model:returnedModel,
        system_fingerprint:fingerprint,raw_sse:raw,raw_usage:usage,complete:done,
        elapsed_seconds:(performance.now()-requestStarted)/1000});
      const error=!response.ok?'HTTP '+response.status:!done?'incomplete SSE':!usage?'missing provider usage':null;
      const attemptId=reserved.attempt_id;reserved=null;
      await rpc('settle',{attempt_id:attemptId,usage,error});
      phase('模型响应已记录，DSH解析及调度');
      if (error) fail('NETWORK_STOP',error);
      return new Response(raw,{status:response.status,statusText:response.statusText,headers:response.headers});
    } catch(error) {
      if (reserved && !blocked) {
        try {await rpc('settle',{attempt_id:reserved.attempt_id,error:String(error.message)});} catch {}
      }
      log('http.jsonl',{event:'blocked_or_failed',turn_id:currentTurn,code:error.code||null,message:error.message,
        elapsed_seconds:requestStarted===null?null:(performance.now()-requestStarted)/1000});
      phase('模型请求被阻止或失败，本次不再请求');
      if (['model_limit','tool_limit','session_budget','body_limit'].includes(error.code)) turnBlocked=true;
      else blocked=true;
      throw error;
    }
  };
  ctx.on('dispose',()=>{globalThis.fetch=originalFetch;invalidate('DSH disposed');readline.close();child.stdin.end();child.kill();});
  catalogue=await rpc('catalog');
  phase('真实MCP工具发现完成，等待用户轮');
  if (stable(catalogue.map(t=>t.name).sort())!==stable([...names].sort())) fail('CATALOG','not exactly ten capabilities');
  log('plugin.jsonl',{event:'effective_catalog',catalogue,tools_mode:'native',model_loop:'DSH release agent-loop'});
  for (const tool of catalogue) ctx.tools.register({
    name:tool.name,description:tool.description,parameters:tool.input_schema,
    // Output metadata is NOT sent as function parameters. Return one envelope.
    output:{schema:{type:'object'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
    timeoutMs:600000,isConcurrencySafe:()=>false,
    execute:async(args,exec)=>{
      const callTurn=turn().turn_id;
      const admission=toolAdmissions.get(String(exec.callId));
      if (!admission || admission.reason || admission.turn!==callTurn)
        fail('TOOL_ADMISSION','tool execution lacks its current synchronous guard admission');
      if (!contextReady && tool.name==='inspect_context' && ++contextAttempts>2)
        fail('CONTEXT_LIMIT','At most one context parameter correction is allowed');
      const outcome=await admission.promise;
      if (outcome.error) throw outcome.error;
      phase('正在调用工具 '+tool.name);
      const result=await rpc('tool',{name:tool.name,arguments:args,tool_call_id:String(exec.callId)},exec.signal);
      const returnedTurn=turn().turn_id;
      const releasesContext=callTurn===returnedTurn && tool.name==='inspect_context'
        && result.tool_name==='inspect_context' && result.error===null && result.status==='ok'
        && typeof result.evidence_id==='string' && result.evidence_id.length>0;
      if (releasesContext) {contextReady=true;contextEvidenceId=result.evidence_id;}
      // The bridge has already bound this result to the trusted frozen asset,
      // actual MCP arguments, session and turn before returning it to this RPC.
      const releasesDiscovery=callTurn===returnedTurn && contextReady
        && tool.name==='query_association_rules' && args.evaluation_id==='discovery_V1_V3'
        && result.tool_name==='query_association_rules' && result.turn_id===callTurn
        && result.validated_arguments?.evaluation_id==='discovery_V1_V3'
        && result.validated_arguments?.rule_set_id===args.rule_set_id
        && result.error===null && ['ok','no_rules','no_eligible_baskets','restricted_granularity'].includes(result.status)
        && typeof result.evidence_id==='string' && result.evidence_id.length>0;
      if (releasesDiscovery) {discoveryReady=true;discoveryEvidenceId=result.evidence_id;}
      log('tools.jsonl',{event:'result',turn_id:callTurn,current_turn_id:returnedTurn,
        context_released:releasesContext,discovery_released:releasesDiscovery,
        tool_call_id:String(exec.callId),name:tool.name,arguments:args,result});
      phase('工具 '+tool.name+' 已返回，等待DSH后续步骤');
      return result;
    }
  });
  // The locked DSH runtime calls guard(exec) synchronously. A Promise here
  // would itself be a denial. Queue accounting, await it before execution and
  // before any subsequent HTTP, while returning only a string or undefined.
  ctx.tools.guard(exec=>{
    const id=String(exec.callId);
    if (toolAdmissions.has(id)) return toolAdmissions.get(id).reason;
    let reason, promise=null;
    try {
      turn();
      if (blocked || closed || turnBlocked) reason='Task13 run or turn stopped';
      else if (turn().answer_repair) reason='Answer correction cannot call tools';
      else {
        toolCount++;taskToolCount++;
        promise=rpc('tool_attempt',{call_id:id}).then(result=>({result}),error=>({error}));
        if (toolCount>12 || taskToolCount>24) {reason='Task13 tool limit reached';turnBlocked=true;}
        else if (!names.includes(exec.name)) reason='Task12 capability not authorized: '+exec.name;
        else if (!contextReady && exec.name!=='inspect_context') reason='Task12 requires current public context first';
      }
    } catch(error) {reason=error.message;}
    toolAdmissions.set(id,{reason,promise,turn:currentTurn});
    log('tools.jsonl',{event:'guard',turn_id:currentTurn,tool_call_id:String(exec.callId),name:exec.name,denied:reason||null,count:toolCount});
    return reason;
  });
  ctx.on('agent/request',async (_event,next)=>({...await next(),temperature:0}));
  ctx.on('llm/stream',async function*(options,next) {
    turn();
    if (blocked || options.provider!=='deepseek-official' || options.model!=='deepseek-flash' || options.reasoningEffort!=='off'
        || options.maxTokens!==4096 || options.temperature!==0) fail('LLM_CONFIG','frozen request configuration mismatch');
    ensureTools(options.tools);
    log('dsh_stream.jsonl',{event:'request',turn_id:currentTurn,options:{...options,signal:undefined}});
    let lastUsage=null;
    for await (const chunk of next()) {
      if (chunk.type==='usage') lastUsage=chunk;
      log('dsh_stream.jsonl',{event:'chunk',turn_id:currentTurn,chunk});
      yield chunk;
    }
    log('dsh_stream.jsonl',{event:'normalized_usage_final',turn_id:currentTurn,usage:lastUsage,
      note:'DSH inputTokens is uncached input; cacheReadTokens/cacheWriteTokens separate; not provider raw usage'});
  });
  if (cfg.mode==='offline' && cfg.network_probe) {
    try {await globalThis.fetch('https://example.invalid/task13-network-probe');}
    catch(error) {log('plugin.jsonl',{event:'offline_external_probe_denied',code:error.code,message:error.message});}
  }
}
