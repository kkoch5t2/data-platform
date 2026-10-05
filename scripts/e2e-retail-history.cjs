const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:4324';
(async()=>{
 const dataset=JSON.parse(fs.readFileSync('public/data/retail-prices-city-monthly.json','utf8'));
 assert.equal(dataset.months[0],'2000-01');
 const rice=dataset.values['1001']['13100'];
 assert.equal(rice[0],2961);
 const expected=rice.at(-1)-rice[0];
 const browser=await chromium.launch({headless:true});let checks=0;
 try{
  for(const [name,viewport] of [['desktop',{width:1440,height:960}],['mobile',{width:390,height:844}]]){
   const context=await browser.newContext({viewport});const page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   const response=await page.goto(base+'/economy-prices/?tab=city-prices&retailPeriod=all&retailItem=1001',{waitUntil:'domcontentloaded'});
   assert.equal(response.status(),200);
   await page.waitForFunction(()=>document.querySelector('#city-price-change')?.textContent.includes('2000年1月'));
   assert.equal(await page.locator('#city-price-period').inputValue(),'all');
   assert((await page.locator('#city-price-change').textContent()).includes('+'+expected.toLocaleString('ja-JP')+'円'));
   assert((await page.locator('#city-price-unit-note').textContent()).includes('10kg原値を5kg相当'));
   assert((await page.locator('#city-price-rank-title').textContent()).includes('安い都市'));
   const ordered=dataset.cities.map(c=>({name:c.name,value:dataset.values['1001'][c.code]?.at(-1)})).filter(x=>x.value!=null).sort((a,b)=>a.value-b.value);
   assert((await page.locator('#city-price-rank-sub').textContent()).includes(ordered[0].name));
   assert(await page.locator('#city-price-history-chart canvas').count()>0);
   assert(await page.locator('#city-price-rank-chart canvas').count()>0);
   const rank=dataset.cities.map(c=>dataset.values['1001'][c.code]?.at(-1)).filter(v=>v!=null).sort((a,b)=>a-b);
   assert(rank[0]<=rank[1],'data can be ranked cheapest first');
   const dir=path.join(process.cwd(),'tmp/retail-history-screens');fs.mkdirSync(dir,{recursive:true});
   await page.screenshot({path:path.join(dir,name+'-all.png'),fullPage:true});
   await page.locator('#city-price-order').selectOption('high');
   assert((await page.locator('#city-price-rank-title').textContent()).includes('高い都市'));
   assert((await page.locator('#city-price-rank-sub').textContent()).includes(ordered.at(-1).name));
   await page.locator('#city-price-item').selectOption('1341');
   assert((await page.locator('#city-price-unit-note').textContent()).includes('比較から除外'));
   await page.locator('#city-price-period').selectOption('24');
   assert.equal(await page.locator('#city-price-period').inputValue(),'24');
   assert((await page.locator('#city-price-change').textContent()).includes('から'));
   await page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),name+' horizontal overflow');
   assert.deepEqual(errors,[],name+' page errors');
   checks+=15;await context.close();
  }
  console.log(JSON.stringify({base,checks,failures:0}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
