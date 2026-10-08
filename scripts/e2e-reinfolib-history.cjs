const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:4324';
(async()=>{
 const index=JSON.parse(fs.readFileSync('public/data/realestate-history/index.json'));
 const tokyo=JSON.parse(fs.readFileSync('public/data/realestate-history/13.json'));
 const browser=await chromium.launch({headless:true});let checks=0;
 try{for(const [name,width] of [['desktop',1440],['mobile',390],['small',320]]){
  const context=await browser.newContext({viewport:{width,height:960}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const response=await page.goto(base+'/realestate/',{waitUntil:'domcontentloaded'});
  assert.equal(response.status(),200);
  await page.waitForFunction(()=>document.querySelector('#trade-history-status').textContent.includes('2005Q3'));
  assert((await page.locator('#trade-history-status').textContent()).includes(index.latestPeriod));
  assert.equal(await page.locator('#trade-history-pref option').count(),48);
  const first=index.periods.find(p=>index.quarterly[p].land.count>=5&&index.quarterly[p].land.medianUnitPrice!=null);
  assert((await page.locator('#trade-history-values').textContent()).includes(index.quarterly[first].land.medianUnitPrice.toLocaleString('ja-JP')+'円/㎡'));
  assert(await page.locator('#trade-history-chart canvas').count()>0);
  await page.locator('#trade-history-pref').selectOption('13');
  await page.waitForFunction(()=>document.querySelector('#trade-history-status').textContent.startsWith('東京都'));
  assert.equal(await page.locator('#trade-history-city option').count(),tokyo.municipalities.length+1);
  const m=tokyo.municipalities.find(x=>Object.values(x.quarterly).some(s=>s.land.count>=5));
  await page.locator('#trade-history-city').selectOption(m.id);
  assert((await page.locator('#trade-history-status').textContent()).startsWith(m.name));
  await page.locator('#trade-history-range').selectOption('20');
  assert((await page.locator('#trade-history-status').textContent()).includes(index.periods.at(-20)));
  await page.locator('#trade-history-segment').selectOption('house');
  assert((await page.locator('#trade-history-values').textContent()).includes('円'));
  await page.locator('#trade-history-range').selectOption('all');
  await page.locator('#trade-history-pref').selectOption('');
  assert((await page.locator('#trade-history-status').textContent()).startsWith('全国'));
  assert(await page.locator('#trade-history-city').isDisabled());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  assert.deepEqual(errors,[]);
  fs.mkdirSync('tmp/reinfolib-history-screens',{recursive:true});
  await page.locator('.history').screenshot({path:'tmp/reinfolib-history-screens/'+name+'.png'});
  // New uncached prefecture request failure must not leave a stale chart.
  await page.route('**/data/realestate-history/01.json',r=>r.fulfill({status:503,body:'unavailable'}));
  await page.locator('#trade-history-pref').selectOption('01');
  await page.waitForFunction(()=>document.querySelector('#trade-history-status').textContent.includes('取得できません'));
  assert.equal(await page.locator('#trade-history-values').textContent(),'');
  await page.locator('#trade-history-segment').selectOption('condo');
  assert((await page.locator('#trade-history-status').textContent()).includes('取得できません'));
  assert.equal(await page.locator('#trade-history-values').textContent(),'');
  checks+=15;await context.close();
 }console.log(JSON.stringify({base,checks,failures:0}));}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
