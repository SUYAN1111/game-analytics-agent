// Real installed Chrome, isolated ephemeral profile; loopback backend only.
import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const testRoot=process.env.WEB_TEST_OUTPUT||'state/task15';
const output=path.resolve(testRoot,'screenshots');
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
const page=await context.newPage();
const failures=[],checks=[];
page.on('pageerror',error=>failures.push(String(error)));
page.on('request',req=>{assert.ok(new URL(req.url()).hostname==='127.0.0.1','browser must use loopback only');});
const base=process.env.WEB_TEST_URL||'http://127.0.0.1:8765';
const shot=async name=>{await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(output,name+'.png'),fullPage:!name.includes('evidence')});checks.push(name);console.log('SCREENSHOT '+name);};
const waitDone=async()=>{await page.locator('.turn .status.verified').last().waitFor({timeout:900000});};
const checkMethod=async(key,algorithm)=>{
  const panel=page.locator('.turn').last().locator('.analysis-methods');
  assert.equal(await panel.evaluate(e=>e.open),false,'methods should not obscure the main result');
  await panel.locator(':scope > summary').focus();await page.keyboard.press('Enter');
  const card=panel.locator(`[data-method="${key}"]`);await card.waitFor();
  assert.ok((await card.innerText()).includes('适用范围与限制'));
  const technical=card.locator('.method-technical');
  assert.equal(await technical.evaluate(e=>e.open),false);
  await technical.locator('summary').click();assert.ok((await technical.innerText()).includes(algorithm));
  if(key==='prediction')assert.ok((await card.innerText()).includes('决策树没有参与这次预测'));
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'expanded method has no mobile overflow');
  await shot(`method-${key}-mobile`);
  await page.setViewportSize({width:1440,height:1000});await technical.locator('summary').click();
  await shot(`method-${key}-desktop`);
  await card.locator('.method-evidence').click();await page.getByRole('dialog',{name:'证据详情'}).waitFor();
  await page.locator('.evidence-readable').waitFor();
  const sourceButton=card.locator('.method-evidence');
  await page.getByRole('button',{name:'关闭证据',exact:true}).click();
  assert.equal(await sourceButton.evaluate(e=>e===document.activeElement),true);
  await panel.locator(':scope > summary').click();
};
const fresh=async()=>{await page.getByRole('button',{name:'＋ 新建对话',exact:true}).click();await page.locator('.welcome').waitFor();};
const sendExample=async (tab,question)=>{
  const before=await page.locator('.turn').count();
  await page.locator('#question-picker').getByRole('button',{name:tab,exact:true}).click();
  await page.locator('#question-picker').getByRole('button',{name:question,exact:true}).click();
  assert.equal(await page.locator('#question').inputValue(),question);
  assert.equal(await page.locator('.turn').count(),before,'example must fill without execution');
  await page.getByRole('button',{name:'发送问题',exact:true}).click();
};
const waitReserved=async()=>{
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    const h=await context.request.get(base+'/api/health').then(r=>r.json());
    if(h.budget.reserved_unknown_cny>0)return;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('real provider reservation was not observed');
};
const report=path.resolve(testRoot+'/' +(process.argv.includes('--cancel-only')?'browser-cancel-results.json':'browser-results.json'));
try{
  await page.goto(base);await page.getByRole('button',{name:'版本对比',exact:true}).waitFor();
  assert.equal(await page.locator('.direction-options button').count(),5);
  await page.setViewportSize({width:390,height:844});
  const questionBox=await page.locator('#question').boundingBox();assert.ok(questionBox.y+questionBox.height<=844,'question input must be visible on the initial mobile screen');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await shot('00-home-mobile');
  await page.setViewportSize({width:1440,height:1000});
  await shot('01-home-1440');
  if(!process.argv.includes('--cancel-only')&&!process.argv.includes('--home-only')){
    const draft='我想看看探索地图的玩家最近玩得怎么样';
    await page.locator('#question').fill(draft);
    for(const name of ['版本对比','参与预测','玩家分组','玩法关联','指标说明']){
      await page.getByRole('button',{name,exact:true}).click();assert.equal(await page.locator('#question').inputValue(),draft);
    }
    await page.getByRole('button',{name:'剧情开始情况是怎么算出来的？',exact:true}).click();
    assert.equal(await page.locator('#question').inputValue(),draft);
    await page.getByRole('button',{name:'保留我的问题',exact:true}).click();assert.equal(await page.locator('#question').inputValue(),draft);
    await page.getByRole('button',{name:'剧情开始情况是怎么算出来的？',exact:true}).click();
    await page.getByRole('button',{name:'替换输入内容',exact:true}).click();
    assert.equal(await page.locator('#question').inputValue(),'剧情开始情况是怎么算出来的？');assert.equal(await page.locator('.turn').count(),0);
    await page.locator('#question').fill(draft);const before=await context.request.get(base+'/api/health').then(r=>r.json());
    await page.getByRole('button',{name:'发送问题',exact:true}).click();await page.getByRole('button',{name:'修改这个问题',exact:true}).waitFor();
    assert.ok((await page.locator('.user-message').innerText()).includes(draft));assert.equal(await page.locator('.result-overview').count(),0);
    await page.getByRole('button',{name:'修改这个问题',exact:true}).click();assert.equal(await page.locator('#question').inputValue(),draft);
    const after=await context.request.get(base+'/api/health').then(r=>r.json());assert.equal(after.budget.request_count,before.budget.request_count);
    await shot('01a-question-retained');await fresh();
  }
  if(process.argv.includes('--cancel-only')){
    await fresh();await page.locator('#question').fill('测试：慢响应与取消');
    await page.getByRole('button',{name:'发送问题',exact:true}).click();await waitReserved();
    await page.setViewportSize({width:390,height:844});await shot('13-mobile-running-390');
    await page.locator('.execution li[data-code="model_started"]').waitFor({timeout:15000});
    let releaseCancel;const cancelGate=new Promise(r=>releaseCancel=r);
    await page.route('**/api/jobs/*/cancel',async route=>{await cancelGate;await route.continue();});
    await page.getByRole('button',{name:'取消任务',exact:true}).click();
    await page.getByRole('button',{name:'正在发送停止请求…',exact:true}).waitFor();
    assert.equal(await page.locator('.readonly:visible').count(),0,'pending control request must not claim the session is already closed');
    releaseCancel();
    await page.getByText('本次任务已取消，此对话已结束，可新建对话。',{exact:true}).waitFor({timeout:60000});
    await page.unroute('**/api/jobs/*/cancel');
    await page.locator('.execution summary').click();
    assert.ok((await page.locator('.execution li[data-code="model_started"]').innerText()).includes('未完成'),'cancelled model wait is not a completed step');
    await page.getByText('本次体验的可用额度已暂停，请联系管理员后再试。已完成的分析仍可查看。',{exact:true}).waitFor({timeout:15000});
    const h=await context.request.get(base+'/api/health').then(r=>r.json());
    assert.ok(h.budget.stopped&&h.budget.reserved_unknown_cny>0);await shot('14-mobile-cancelled-390');
  }
  else if(process.argv.includes('--home-only')) process.exitCode=0;
  else{
    await sendExample('版本对比','比较两个版本的剧情开始情况');
    await page.getByRole('button',{name:'取消任务',exact:true}).waitFor({timeout:15000});
    await shot('02-running-1440');
    await waitDone();assert.ok(await page.locator('table').count());
    assert.equal(await page.locator('.welcome').count(),0,'welcome should give way to the conversation');
    assert.equal(await page.locator('#question-picker').isVisible(),false,'initial question picker collapses after sending');
    assert.equal(await page.locator('.detailed-data').evaluate(e=>e.open),false);
    assert.equal(await page.locator('.source-list').evaluate(e=>e.open),false);
    const sid=await page.evaluate(()=>localStorage.getItem('selectedSession'));
    const session=await context.request.get(base+'/api/sessions/'+sid).then(r=>r.json());
    const facts=session.jobs[0].evidence.filter(e=>e.kind==='claims').map(e=>e.fact);
    const overview=await page.locator('.result-overview').innerText();
    for(const fact of facts.filter(f=>f.field==='rate'||f.field==='percentage_point_difference'))assert.ok(overview.includes(fact.rendered_value),'overview uses host-verified numbers');
    await page.locator('.result-overview .reading-card button').first().click();await page.getByRole('dialog',{name:'证据详情'}).waitFor();await page.getByRole('button',{name:'关闭证据',exact:true}).click();
    await page.locator('.detailed-data>summary').click();assert.ok(await page.locator('.result-data table').isVisible());await page.locator('.detailed-data>summary').click();
    await page.locator('.verified-text summary').click();await shot('03a-long-answer-1440');await page.locator('.verified-text summary').click();
    await shot('03-metric-result-1440');
    await checkMethod('metric','比例统计与差值比较');
    if(!await page.locator('.evidence-links button').first().isVisible())await page.locator('.source-list>summary').first().click();await page.locator('.evidence-links button').first().click();
    await page.getByRole('dialog',{name:'证据详情'}).waitFor();await shot('04-metric-evidence-1440');
    await page.getByRole('button',{name:'关闭证据',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'↗ 指标证据 1');
    await context.grantPermissions(['clipboard-read','clipboard-write']);
    await page.getByRole('button',{name:'复制回答',exact:true}).click();
    await page.getByText('已复制回答和数据来源。',{exact:true}).waitFor();
    assert.ok((await page.evaluate(()=>navigator.clipboard.readText())).includes('模拟数据演示'));
    const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'下载分析',exact:true}).click();
    const download=await downloadPromise;await download.saveAs(path.resolve(testRoot,'export.md'));
    const exported=await fs.readFile(path.resolve(testRoot,'export.md'),'utf8');
    assert.ok(exported.includes('模拟数据演示')&&exported.includes('本轮公开证据'));
    assert.ok(exported.includes('分析方法（产品说明）')&&exported.includes('只有统计范围一致时才适合比较'));
    assert.ok(!/DEEPSEEK_API_KEY|\\Users\\|\\sessions\\|"auth"\s*:/.test(exported));
    await page.getByRole('button',{name:'这些结果能说明因果关系吗？',exact:true}).click();
    assert.equal(await page.locator('.turn').count(),1);
    await page.getByRole('button',{name:'发送问题',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.status.verified').length===2,{},{timeout:180000});
    if(!await page.locator('.evidence-links button').first().isVisible())await page.locator('.source-list>summary').first().click();await page.locator('.evidence-links button').first().click();await page.getByRole('dialog',{name:'证据详情'}).waitFor();
    assert.ok((await page.locator('.evidence-readable').innerText()).includes('前一次更新'));
    await page.getByRole('button',{name:'关闭证据',exact:true}).click();
    await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.status.verified').length===2);
    await fresh();await sendExample('指标说明','剧情开始情况是怎么算出来的？');await waitDone();await shot('05-knowledge-1440');
    await checkMethod('knowledge','资料检索与引用核对');
    await fresh();await sendExample('参与预测','查看示例数据中的剧情参与预测');await waitDone();await page.setViewportSize({width:1280,height:900});await shot('06-prediction-1280');
    await checkMethod('prediction','逻辑回归');
    await fresh();await sendExample('玩家分组','不同玩家的游戏习惯有什么区别？');await waitDone();
    assert.equal(await page.locator('.group-card').count(),3);assert.equal(await page.locator('.group-card .reading-card').count(),9);
    await page.setViewportSize({width:1280,height:900});await shot('07-segments-wide-table-1280');
    await checkMethod('cluster','K-means');
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile document overflow');
    await shot('08-mobile-result-390');if(!await page.locator('.evidence-links button').first().isVisible())await page.locator('.source-list>summary').first().click();await page.locator('.evidence-links button').first().click();await shot('09-mobile-evidence-390');
    await page.getByRole('button',{name:'关闭证据',exact:true}).click();
    await fresh();await sendExample('玩法关联','玩休闲小游戏的玩家，也会玩协作玩法吗？');await waitDone();await shot('10-mobile-rules-390');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:1440,height:1000});await shot('11-rules-1440');
    await checkMethod('rules','Apriori');
    await fresh();await page.locator('#question').fill('测试：错误模型回复');await page.getByRole('button',{name:'发送问题',exact:true}).click();
    await page.locator('.failure').waitFor({timeout:180000});assert.ok((await page.locator('.failure').innerText()).includes('核对'));await shot('12-failure-1440');
    assert.equal(await page.locator('.analysis-methods').count(),0,'failed answers have no method assertions');
    await fresh();await page.locator('#question').fill('测试：慢响应与取消');
    await page.locator('#question').dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true,keyCode:229});
    assert.equal(await page.locator('.turn').count(),0,'IME composition must not send');
    await page.getByRole('button',{name:'发送问题',exact:true}).click();
    await page.getByRole('button',{name:'取消任务',exact:true}).waitFor({timeout:15000});
    // Ensure cancellation exercises an actual reserved HTTP request, not just startup.
    await waitReserved();
    await page.setViewportSize({width:390,height:844});await shot('13-mobile-running-390');
    await page.getByRole('button',{name:'取消任务',exact:true}).click();
    await page.getByText('本次任务已取消，此对话已结束，可新建对话。',{exact:true}).waitFor({timeout:60000});
    await page.getByText('本次体验的可用额度已暂停，请联系管理员后再试。已完成的分析仍可查看。',{exact:true}).waitFor({timeout:15000});
    await shot('14-mobile-cancelled-390');
    assert.equal(failures.length,0,failures.join('\n'));
  }
  await fs.writeFile(report,JSON.stringify({status:'PASS',browser:await browser.version(),mode:'offline real DSH/MCP',screenshots:checks,page_errors:failures},null,2));
}catch(error){await shot('failure-debug');await fs.writeFile(report,JSON.stringify({status:'FAIL',error:String(error),screenshots:checks,page_errors:failures},null,2));throw error;}
finally{await browser.close();}
