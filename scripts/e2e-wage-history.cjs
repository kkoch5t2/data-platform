const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const {goto,reload}=require('./e2e-navigation.cjs');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:4326';
(async()=>{
 const data=JSON.parse(fs.readFileSync('public/data/employment-wage-history.json'));
 const browser=await chromium.launch({headless:true});let checks=0;
 try{for(const [name,width] of [['desktop',1440],['mobile',390],['small',320]]){
  const context=await browser.newContext({viewport:{width,height:960}}),page=await context.newPage(),errors=[];let requests=0;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/data/employment-wage-history.json'))requests++});
  await goto(page,base+'/employment-economy/');assert.equal(requests,0);
  await page.locator('[data-tab="wage-history"]').click();
  await page.waitForFunction(()=>document.querySelector('#wage-history-values tbody')?.rows.length===25);
  assert.equal(requests,1);assert.equal(await page.locator('#wage-history-chart canvas').count(),1);
  await page.locator('#compare').selectOption('大阪府');
  for(const metric of ['monthlyCashSalaryThousandYen','annualBonusThousandYen','estimatedAnnualCashThousandYen']){
   await page.locator('#wage-history-metric').selectOption(metric);
   const idx=data.fields.indexOf(metric),tokyo=data.records.find(r=>r.prefecture==='東京都').values[0];
   assert((await page.locator('#wage-history-values tbody tr').first().textContent()).includes((tokyo[idx]*.1).toLocaleString('ja-JP',{maximumFractionDigits:2})));
   assert((await page.locator('#wage-history-values thead').textContent()).includes('大阪府'));checks+=2;
  }
  await page.locator('#wage-history-start').selectOption('2020');
  assert.equal(await page.locator('#wage-history-values tbody tr').count(),6);
  const url=page.url();await reload(page);
  await page.waitForFunction(()=>document.querySelector('#wage-history-values tbody')?.rows.length===6);
  assert.equal(await page.locator('#compare').inputValue(),'大阪府');assert.equal(await page.locator('#wage-history-start').inputValue(),'2020');
  assert.equal(page.url(),url);
  await page.locator('#wage-history-start').selectOption('2001');
  assert.equal(await page.locator('#wage-history-values tbody a').count(),25);
  assert((await page.locator('#wage-history-note').textContent()).includes('原則として調査前年'));
  assert((await page.locator('#wage-history-note').textContent()).includes('2020年'));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  fs.mkdirSync('tmp/wage-history-screens',{recursive:true});
  await page.locator('[data-panel="wage-history"]').screenshot({path:'tmp/wage-history-screens/'+name+'.png'});
  assert.deepEqual(errors,[]);await context.close();checks+=12;
  const failContext=await browser.newContext({viewport:{width,height:960}}),failure=await failContext.newPage();
  await failure.route('**/data/employment-wage-history.json',r=>r.fulfill({status:503,body:'unavailable'}));
  await goto(failure,base+'/employment-economy/?tab=wage-history');
  await failure.waitForFunction(()=>document.querySelector('#wage-history-note').textContent.includes('読み込めません'));
  assert.equal(await failure.locator('#wage-history-values tbody tr').count(),0);
  await failure.unroute('**/data/employment-wage-history.json');
  await failure.locator('[data-tab="overview"]').click();await failure.locator('[data-tab="wage-history"]').click();
  await failure.waitForFunction(()=>document.querySelector('#wage-history-values tbody')?.rows.length===25);
  checks+=2;await failContext.close();
 }console.log(JSON.stringify({base,checks,failures:0}));}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
