import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),out=path.resolve('state/task15-delete'),period='delete-'+Date.now(),port=8768,base=`http://127.0.0.1:${port}`;
const home=path.resolve('state/web/offline',period),python=path.resolve('.venv-core/Scripts/python.exe');
await fs.mkdir(out,{recursive:true});let server;const checks=[],errors=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(){
  server=spawn(python,['-B','-m','web_api','--mode','offline','--port',String(port),'--period',period],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,DEEPSEEK_API_KEY:'',PYTHONUTF8:'1'}});
  server.stdout.on('data',()=>{});server.stderr.on('data',s=>fs.appendFile(path.join(out,'server.log'),s));
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)return;}catch{}if(server.exitCode!==null)throw new Error('server exited');await pause(200);}throw new Error('startup timeout');
}
async function stop(){if(!server||server.exitCode!==null)return;await fs.writeFile(path.join(home,'stop.request'),'stop');for(let i=0;i<300&&server.exitCode===null;i++)await pause(100);assert.equal(server.exitCode,0,'service closes cleanly');}
const browser=await chromium.launch({channel:'chrome',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
page.on('pageerror',e=>errors.push(String(e)));const headers={Origin:base};
const get=async url=>(await context.request.get(base+url)).json();
const post=async(url,data={})=>context.request.post(base+url,{data,headers});
const row=id=>page.locator(`.history-row[data-session-id="${id}"]`);
async function del(id,accept=true){page.once('dialog',d=>accept?d.accept():d.dismiss());await row(id).getByRole('button',{name:/删除对话/}).click();if(accept)await row(id).waitFor({state:'detached',timeout:45000});}
function databaseCounts(sid,jid){const r=spawnSync(python,['-B','-c',`import sqlite3,json,sys
db=sqlite3.connect(sys.argv[1]);sid,jid=sys.argv[2:4]
print(json.dumps([db.execute('SELECT count(*) FROM '+t+' WHERE '+c+'=?',(v,)).fetchone()[0] for t,c,v in [('sessions','id',sid),('jobs','session_id',sid),('evidence','session_id',sid),('events','job_id',jid)]]))`,path.join(home,'web.sqlite3'),sid,jid],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
try{
  await start();await page.goto(base);await page.getByRole('button',{name:'玩家分组',exact:true}).waitFor();
  const keep=(await (await post('/api/sessions')).json()).id;
  await page.getByRole('button',{name:'＋ 新建对话',exact:true}).click();await page.locator('.history-row').nth(1).waitFor();
  const empty=(await get('/api/sessions')).find(s=>s.id!==keep).id;
  await del(empty,false);assert.equal((await context.request.get(base+'/api/sessions/'+empty)).status(),200);
  await del(empty);assert.deepEqual(databaseCounts(empty,''),[0,0,0,0]);checks.push('confirmation cancel preserves; empty conversation hard deleted');
  await page.getByRole('button',{name:'＋ 新建对话',exact:true}).click();
  const sid=(await get('/api/sessions')).find(s=>s.id!==keep).id;
  await page.getByRole('button',{name:'玩家分组',exact:true}).click();await page.getByRole('button',{name:'不同玩家的游戏习惯有什么区别？',exact:true}).click();await page.getByRole('button',{name:'发送问题',exact:true}).click();
  await page.locator('.status.verified').waitFor({timeout:180000});
  const session=await get('/api/sessions/'+sid),job=session.jobs[0],e=job.evidence[0];assert.ok(databaseCounts(sid,job.id).every(n=>n>0));
  const before=await get('/api/health');const other=await browser.newContext();
  assert.equal((await other.request.post(base+'/api/sessions/'+sid+'/delete',{data:{},headers})).status(),404);await other.close();
  assert.equal((await context.request.post(base+'/api/sessions/'+sid+'/delete',{data:{},headers:{Origin:'https://example.org'}})).status(),403);
  assert.equal((await post('/api/sessions/'+sid+'/delete',{unexpected:true})).status(),422);checks.push('owner, origin and request validation');
  await stop();await start();await page.reload();await row(sid).waitFor();assert.equal((await get('/api/sessions/'+sid)).status,'read_only');
  await page.screenshot({path:path.join(out,'01-delete-button-desktop.png'),fullPage:true});
  await del(sid);assert.deepEqual(databaseCounts(sid,job.id),[0,0,0,0]);
  for(const uri of ['/api/sessions/'+sid,'/api/jobs/'+job.id,`/api/sessions/${sid}/turns/${job.turn_id}/evidence/${e.id}`])assert.equal((await context.request.get(base+uri)).status(),404);
  assert.equal(await page.evaluate(()=>localStorage.getItem('selectedSession')),null);assert.equal((await context.request.get(base+'/api/sessions/'+keep)).status(),200);
  assert.deepEqual((await get('/api/health')).budget,before.budget);await stop();await start();await page.reload();await row(keep).waitFor();assert.equal(await row(sid).count(),0);assert.deepEqual(databaseCounts(sid,job.id),[0,0,0,0]);checks.push('read-only history, messages, events and evidence removed; restart persistence; other session and ledger unchanged');
  // Delete a queued session while another real provider request is in flight.
  const running=(await (await post('/api/sessions')).json()).id;
  await post('/api/sessions/'+running+'/turns',{text:'测试：慢响应与取消',idempotency_key:crypto.randomUUID()});
  for(let i=0;i<200;i++){if((await get('/api/health')).budget.reserved_unknown_cny>0)break;await pause(100);}
  assert.ok((await get('/api/health')).budget.reserved_unknown_cny>0);
  const queued=(await (await post('/api/sessions')).json()).id;
  const qjob=await (await post('/api/sessions/'+queued+'/turns',{text:'不同玩家的游戏习惯有什么区别？',idempotency_key:crypto.randomUUID()})).json();
  assert.equal(qjob.status,'queued');assert.equal((await post('/api/sessions/'+queued+'/delete')).status(),200);assert.deepEqual(databaseCounts(queued,qjob.id),[0,0,0,0]);
  await page.reload();await row(running).waitFor();await row(running).locator('.history').click();await page.getByRole('button',{name:'取消任务',exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'02-delete-button-mobile.png'),fullPage:true});
  const runningJob=(await get('/api/sessions/'+running)).jobs[0];await del(running);assert.deepEqual(databaseCounts(running,runningJob.id),[0,0,0,0]);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.equal((await context.request.get(base+'/api/sessions/'+keep)).status(),200);
  assert.equal((await get('/api/health')).budget.stopped,true);await page.reload();await row(keep).waitFor();assert.equal(await row(running).count(),0);assert.deepEqual(errors,[]);checks.push('queued and running deletions; worker safely stopped; budget reservation retained; mobile layout');
  await page.screenshot({path:path.join(out,'03-after-delete.png'),fullPage:true});
  await fs.writeFile(path.join(out,'results.json'),JSON.stringify({status:'PASS',period,checks,errors},null,2));console.log('PASS',checks);
}catch(e){await fs.writeFile(path.join(out,'results.json'),JSON.stringify({status:'FAIL',period,checks,errors,error:String(e)},null,2));throw e;}
finally{await browser.close();await stop();}
