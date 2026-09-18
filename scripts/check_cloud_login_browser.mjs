// Public entry + one real analysis with an offline model stub on a local cloud API.
import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {chromium, expect} from '../web/node_modules/@playwright/test/index.mjs';

const origin=process.env.CLOUD_LOGIN_TEST_ORIGIN||'http://127.0.0.1:8767';
const url=new URL(origin);
if(url.protocol!=='http:'||!['127.0.0.1','localhost'].includes(url.hostname)||url.pathname!=='/'||url.search||url.hash||url.username||url.password){
  throw new Error('Use a disposable local cloud API');
}
const output=new URL('../state/cloud-public-browser/',import.meta.url);
await mkdir(output,{recursive:true});
const shell=await readFile(new URL('../web/dist/index.html',import.meta.url),'utf8');
const browser=await chromium.launch({channel:process.env.CLOUD_TEST_BROWSER_CHANNEL||'chrome',headless:true});
const checks=[],errors=[];
try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  // Deliberately reproduce Vercel's static homepage instead of ASGI's login gate.
  await page.route(url.origin+'/',route=>route.fulfill({contentType:'text/html',body:shell}));
  await page.goto(url.origin+'/');
  await expect(page).toHaveURL(url.origin+'/');
  await expect(page.locator('.sidebar-footer')).toContainText('本地模式');
  const health=await context.request.get(url.origin+'/api/health');
  assert.equal((await health.json()).mode,'offline','This test must never submit to a live model');
  await expect(page.locator('input[name="code"]')).toHaveCount(0);
  const owner=(await context.cookies()).find(c=>c.name==='web_owner')?.value;
  assert.match(owner,/^[0-9a-f]{64}$/);
  assert((await context.cookies()).some(c=>c.name==='web_owner_signature'&&c.httpOnly));
  assert(!(await context.cookies()).some(c=>c.name==='app_access'));
  checks.push('fresh visitor opens static homepage directly with signed identity and no login form');
  await page.screenshot({path:fileURLToPath(new URL('home.png',output)),fullPage:true});
  await page.locator('#question').fill('你好');
  let submitted=page.waitForResponse(r=>r.url().endsWith('/turns')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'发送问题',exact:true}).click();
  const greeting=await (await submitted).json();
  assert.equal(greeting.status,'guidance');
  await expect(page.locator('.turn')).toHaveCount(1);
  checks.push('public visitor can send a greeting without a model request');

  await page.locator('#question').fill('比较两个版本的剧情开始情况');
  submitted=page.waitForResponse(r=>r.url().endsWith('/turns')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'发送问题',exact:true}).click();
  const queued=await (await submitted).json();
  assert.equal(queued.status,'queued');
  await expect(page.locator('.status.verified')).toBeVisible({timeout:240000});
  const result=await context.request.get(url.origin+'/api/jobs/'+queued.id).then(r=>r.json());
  assert.equal(result.status,'succeeded');
  assert(result.evidence.length>0);
  checks.push('anonymous browser completes real DSH/MCP comparison through streaming API (offline model)');
  await page.screenshot({path:fileURLToPath(new URL('answer.png',output)),fullPage:true});
  await page.reload();
  await expect(page.locator('.sidebar-footer')).toContainText('本地模式');
  await expect(page.locator('.status.verified')).toBeVisible();
  assert.equal((await context.cookies()).find(c=>c.name==='web_owner')?.value,owner);
  checks.push('refresh restores the public visitor conversation');
  const other=await browser.newContext({viewport:{width:390,height:844}});
  const mobile=await other.newPage();
  mobile.on('pageerror',e=>errors.push(String(e)));
  await mobile.route(url.origin+'/',route=>route.fulfill({contentType:'text/html',body:shell}));
  await mobile.goto(url.origin+'/');
  await expect(mobile.locator('#question')).toBeVisible();
  await expect(mobile.locator('.service-indicator')).toHaveAttribute('data-state','connected');
  assert.equal((await other.request.get(url.origin+'/api/sessions/'+queued.session_id)).status(),404);
  assert((await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)));
  await mobile.screenshot({path:fileURLToPath(new URL('mobile.png',output)),fullPage:true});
  checks.push('mobile visitors enter directly and cannot read another browser history');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('.history-delete').click();
  await expect(page.locator('.history-row')).toHaveCount(0);
  assert.equal((await context.request.get(url.origin+'/api/sessions/'+queued.session_id)).status(),404);
  checks.push('public visitor can actually delete their conversation');
  await page.goto(url.origin+'/_auth');
  await expect(page).toHaveURL(url.origin+'/');
  await expect(page.locator('.sidebar-footer')).toContainText('本地模式');
  checks.push('old login URL redirects to the public workspace');

  const failed=await browser.newContext({viewport:{width:1440,height:1000}});
  const failurePage=await failed.newPage();
  failurePage.on('pageerror',e=>errors.push(String(e)));
  await failurePage.route(url.origin+'/',route=>route.fulfill({contentType:'text/html',body:shell}));
  for(const error of [{status:503,code:'not_configured',message:'云端配置尚未完成，请联系管理员。'},
      {status:401,code:'unrelated',message:'其他认证错误。'}]){
    await failurePage.route('**/api/health',route=>route.fulfill({status:error.status,json:{error}}));
    await failurePage.goto(url.origin+'/');
    await expect(failurePage.locator('.sidebar-footer')).toContainText('服务连接失败');
    assert.equal(new URL(failurePage.url()).pathname,'/');
    await expect(failurePage.locator('.service-indicator')).toHaveAttribute('data-state','failed');
    checks.push(`${error.status}/${error.code} displays failure without redirecting`);
    await failurePage.unroute('**/api/health');
  }
  assert.deepEqual(errors,[]);
  checks.push('no browser script errors');
  const report={status:'PASS',checks,evidence:result.evidence.length,paid_calls:0};
  await writeFile(new URL('result.json',output),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
}finally{await browser.close();}
