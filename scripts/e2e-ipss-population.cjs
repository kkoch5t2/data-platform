const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:4321';
(async()=>{
 const browser=await chromium.launch({headless:true});let checks=0;
 try{
  for(const [name,viewport] of [['desktop',{width:1440,height:950}],['mobile',{width:390,height:844}]]){
   const context=await browser.newContext({viewport});const page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   let response=await page.goto(base+'/regional/',{waitUntil:'domcontentloaded'});
   assert.equal(response.status(),200);assert.equal(await page.locator('a[href="/regional/projections/"]').count(),1);
   response=await page.goto(base+'/regional/projections/',{waitUntil:'domcontentloaded'});
   assert.equal(response.status(),200);await page.waitForFunction(()=>document.querySelector('#kpi-pop')?.textContent.includes('人'));
   assert.equal(await page.locator('#city-a').inputValue(),'13101');
   assert.equal((await page.locator('#kpi-pop').textContent()).trim(),'79,828人');
   await page.locator('#pref-a').selectOption('北海道');await page.locator('#city-a').selectOption('01100');
   assert.equal((await page.locator('#kpi-pop').textContent()).trim(),'1,745,608人');
   await page.locator('#pref-b').selectOption('東京都');await page.locator('#city-b').selectOption('13101');
   assert.equal(await page.locator('#city-b').inputValue(),'13101');
   assert((await page.locator('#kpi-change').textContent()).includes('-11.5%'));
   assert(await page.locator('#trend canvas').count()>0);
   assert(await page.locator('#age canvas').count()>0);
   assert((await page.locator('.note').textContent()).includes('浜通り13市町村'));
   await page.waitForFunction(()=>document.querySelector('#map-status')?.textContent.includes('地点を収録'),{timeout:20000});
   assert(await page.locator('#map canvas').count()>0);
   if(name==='mobile'){
    await page.waitForTimeout(750);let hit=false;const canvas=page.locator('#map canvas');
    for(const y of [.35,.45,.55,.65,.75]){
     for(const x of [.25,.35,.45,.55,.65,.75]){
      const box=await canvas.boundingBox();await canvas.click({position:{x:box.width*x,y:box.height*y},force:true});
      if(await page.getByRole('button',{name:'地域 A に選ぶ'}).count()){
       const popup=await page.locator('.maplibregl-popup').textContent();
       await page.getByRole('button',{name:'地域 A に選ぶ'}).click();
       assert(popup.includes((await page.locator('#kpi-place').textContent()).trim()));
       hit=true;break;
      }
     }
     if(hit)break;
    }
    assert(hit,'map marker popup and selection');
   }
   const dir=path.join(process.cwd(),'tmp/ipss-screens');fs.mkdirSync(dir,{recursive:true});
   await page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),name+' horizontal overflow');
   assert.deepEqual(errors,[],name+' page errors');
   checks+=13;await context.close();
  }
  console.log(JSON.stringify({base,checks,failures:0}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
