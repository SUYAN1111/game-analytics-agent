import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const out=path.resolve('state/ux-stage3'),base=process.env.WEB_TEST_URL||'http://127.0.0.1:8766';await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const shot=async name=>{await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});console.log(name);};
try{
  await page.goto(base);await page.getByRole('button',{name:'版本对比',exact:true}).waitFor();await pause(950);await shot('01-home-desktop');
  const direction=name=>page.getByRole('button',{name,exact:true});
  await direction('版本对比').click();await pause(400);
  const old=await page.locator('.direction-selection').boundingBox();await direction('玩法关联').click();await pause(90);
  const mid=await page.locator('.direction-selection').boundingBox(),target=await direction('玩法关联').boundingBox();
  assert.ok(mid.x>old.x&&mid.x<target.x+1,'selection moves between categories');await pause(420);
  const final=await page.locator('.direction-selection').boundingBox();assert.ok(Math.abs(final.x-target.x)<1&&Math.abs(final.width-target.width)<1);
  checks.push('selection slides and stays aligned; no auto-submit');await shot('02-play-direction');
  const question=page.locator('#question');await question.fill('我想了解玩家的游玩习惯');
  await page.getByRole('button',{name:'发送问题',exact:true}).hover();await pause(400);await shot('03-send-hover');
  const submit=await page.getByRole('button',{name:'发送问题',exact:true}).boundingBox();await page.mouse.move(submit.x+submit.width/2,submit.y+submit.height/2);await page.mouse.down();
  assert.ok(await page.locator('.send .button-ripple').count());await pause(110);await shot('04-send-press');
  // Release outside the control so this visual check does not submit a question.
  await page.mouse.move(submit.x-60,submit.y);await page.mouse.up();await pause(600);assert.equal(await page.locator('.button-ripple').count(),0);
  assert.equal(await page.locator('.turn').count(),0);checks.push('pointer ripple cleans up; pressed state does not delay interaction');
  const short=(await question.boundingBox()).height;await question.fill(Array(12).fill('这是输入框自动增高的检查内容。').join('\n'));await pause(200);
  const tall=(await question.boundingBox()).height;assert.ok(tall>short&&tall<=181);assert.ok(await question.evaluate(e=>e.scrollHeight>e.clientHeight));
  await question.fill('输入框会随着文字恢复高度');await pause(200);assert.ok((await question.boundingBox()).height<tall);checks.push('input grows, caps, scrolls and shrinks');
  await page.setViewportSize({width:390,height:844});await pause(400);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const brand=await page.locator('.brand-name').boundingBox(),newButton=await page.locator('.new-button').boundingBox();assert.ok(newButton.x>brand.x+brand.width&&Math.abs(newButton.y-brand.y)<10,'mobile new button must not overlap history');
  await direction('指标说明').click();await pause(450);const mobile=await page.locator('.direction-selection').boundingBox(),mobileTarget=await direction('指标说明').boundingBox();assert.ok(Math.abs(mobile.x-mobileTarget.x)<1&&Math.abs(mobile.y-mobileTarget.y)<1);await shot('05-mobile-direction');
  checks.push('wrapped mobile selection remains aligned; no horizontal overflow');
  await page.emulateMedia({reducedMotion:'reduce'});await pause(150);
  await direction('版本对比').click();assert.equal(await page.locator('.button-ripple').count(),0);
  assert.equal(await page.locator('.direction-selection').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  assert.equal(await page.evaluate(()=>document.getAnimations().filter(a=>a.playState==='running').length),0);
  await page.keyboard.press('Tab');assert.ok(await page.evaluate(()=>document.activeElement?.tagName==='BUTTON'));
  assert.equal(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'solid');checks.push('reduced motion disables CSS/JS movement; keyboard focus remains visible');
  await shot('06-reduced-motion');assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(out,'motion-results.json'),JSON.stringify({status:'PASS',checks,errors},null,2));
}catch(e){await shot('failure-debug');await fs.writeFile(path.join(out,'motion-results.json'),JSON.stringify({status:'FAIL',checks,errors,error:String(e)},null,2));throw e;}
finally{await context.close();await browser.close();}
