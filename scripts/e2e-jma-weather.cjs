const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const index=JSON.parse(fs.readFileSync('public/data/weather/index.json'));
const base=process.env.E2E_BASE_URL||'https://datlume.com';
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const [name,viewport] of [['desktop',{width:1440,height:900}],['mobile',{width:390,height:844}]]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   const response=await page.goto(base+'/regional/weather/',{waitUntil:'networkidle'});
   assert.equal(response.status(),200);
   await page.locator('#a-value').waitFor();
   await page.waitForFunction(()=>document.querySelector('#a-value').textContent!=='読み込み中');
   assert.equal(await page.locator('#pref').inputValue(),'東京都');
   assert.equal(await page.locator('#station').inputValue(),'s47662');
   assert((await page.locator('#location').innerText()).includes('千代田区'));
   assert((await page.locator('#a-value').innerText()).includes('℃'));
   await page.selectOption('#city','13101');
   assert((await page.locator('#station option').allTextContents()).some(x=>x.includes('東京')));
   await page.selectOption('#station','s47662');
   await page.selectOption('#metric','rainfall');
   assert((await page.locator('#a-value').innerText()).includes('mm'));
   await page.selectOption('#period','monthly');
   assert(new URL(page.url()).searchParams.get('period')==='monthly');
   await page.selectOption('#pref','北海道');
   assert((await page.locator('#station option').count())>20);
   const options=await page.locator('#station option').all();
   await page.selectOption('#compare',await options[1].getAttribute('value'));
   await page.waitForFunction(()=>document.querySelector('#b-value').textContent!=='—');
   assert((await page.locator('#b-value').innerText()).includes('mm'));
   await page.reload({waitUntil:'networkidle'});
   assert.equal(await page.locator('#pref').inputValue(),'北海道');
   assert.equal(await page.locator('#metric').inputValue(),'rainfall');
   assert.equal(await page.locator('#period').inputValue(),'monthly');
   assert.equal(await page.locator('#trend canvas').count(),1);
   assert.equal(errors.length,0,errors.join('; '));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),'horizontal overflow '+name);
   const dir=path.join('tmp','jma-weather-screens');fs.mkdirSync(dir,{recursive:true});
   await page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});
   await context.close();
  }
  console.log('jma weather PC/mobile E2E passed: '+base+' ('+index.stationCount+' stations)');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
