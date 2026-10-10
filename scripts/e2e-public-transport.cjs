const {goto,reload}=require('./e2e-navigation.cjs');
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = (process.env.E2E_BASE_URL || 'http://127.0.0.1:4321').replace(/\/$/,'');
const output = process.env.E2E_SCREENSHOT_DIR || '/tmp/datlume-transport-e2e';
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname,'../public/data/transport',name+'.json')));
const stations=read('stations').records, usage=read('usage'), census=read('commute');
const nf=new Intl.NumberFormat('ja-JP'), decimal=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:1});
async function text(page,id,value){await page.waitForFunction(({id,value})=>document.getElementById(id)?.textContent===value,{id,value});}
async function noOverflow(page){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow');}
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.E2E_CHROMIUM_EXECUTABLE || undefined});
 try {
 for(const width of [1440,390,320]){
  const context=await browser.newContext({viewport:{width,height:1000},acceptDownloads:true});const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().startsWith(base)&&r.status()>=400)errors.push(r.status()+' '+r.url());});
  assert.equal((await goto(page,base+'/transport/')).status(),200);
  await text(page,'station-value','1,333,618人');
  assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://datlume.com/transport/');
  assert.equal(await page.locator('.datlume-brand').getAttribute('href'),'/');
  await noOverflow(page);await page.screenshot({path:path.join(output,'stations-'+width+'.png'),fullPage:true});
  await page.locator('#station-search').fill('新宿');await page.locator('#operator').selectOption('東日本旅客鉄道');
  await page.waitForFunction(()=>document.querySelectorAll('#station-results .result').length===1);
  await page.locator('#station-results .result').click();assert.equal(await page.locator('#station-name').textContent(),'新宿');
  await page.locator('#station-search').fill('存在しない駅123');await page.waitForFunction(()=>document.querySelector('#station-results .empty'));
  await page.locator('#station-search').fill('');await page.locator('#operator').selectOption('');
  const tokyo=stations.find(r=>r.name==='東京'&&r.operator==='東日本旅客鉄道'&&r.values.at(-1)!=null);
  await page.locator('#station-compare').selectOption(tokyo.id);await page.locator('#station-chart-mode').selectOption('index');await page.locator('#station-year').selectOption('2019');
  const downloadPromise=page.waitForEvent('download');await page.locator('#station-csv').click();const download=await downloadPromise;
  const csv=fs.readFileSync(await download.path(),'utf8');assert(csv.includes('"原典駅コード"'));assert(csv.includes('"1333618"'));
  await reload(page,);await page.waitForFunction(()=>document.querySelector('#station-compare').value!=='' && document.querySelector('#station-chart-mode').value==='index');
  assert.equal(await page.locator('#station-year').inputValue(),'2019');assert.equal(await page.locator('#station-compare').inputValue(),tokyo.id);
  await page.locator('#station-year').selectOption('2011');await page.locator('#station-sort').selectOption('growth');await text(page,'result-page','0件');
  // A source-private observation must remain a gap, never zero.
  const missing=stations.find(r=>r.states.includes('private'));
  const gapYear=2011+missing.states.indexOf('private');
  const params=new URLSearchParams({station:missing.id,year:String(gapYear),missing:'1',q:missing.name,operator:missing.operator,line:missing.line});
  await goto(page,base+'/transport/?'+params);await text(page,'station-value','非公開');
  await page.locator('#tab-regions').click();await page.waitForFunction(()=>document.querySelector('#bus-value').textContent.includes('億人'));
  await page.locator('#pref-a').selectOption('北海道');await page.locator('#area-a').selectOption('01100');await page.locator('#bus-pref').selectOption('01');
  const bus=usage.bus.records.find(r=>r.code==='01');await text(page,'bus-value',decimal.format(bus.thousands/1e5)+'億人');
  assert((await page.locator('#commute-sub').textContent()).includes(nf.format(census.records.find(r=>r.code==='01100').total)));
  assert.equal(await page.locator('#commute-table tr').count(),17);
  await noOverflow(page);await page.screenshot({path:path.join(output,'regions-'+width+'.png'),fullPage:true});
  await reload(page,);await page.waitForFunction(()=>document.querySelector('#area-a').value==='01100');assert.equal(await page.locator('#bus-pref').inputValue(),'01');
  await page.locator('#tab-national').click();await text(page,'rail-value',decimal.format(usage.rail.monthly.at(-1).thousands[0]/1e5)+'億人');
  await page.locator('#rail-annual').click();await text(page,'rail-value',decimal.format(usage.rail.annual.at(-1).thousands[0]/1e5)+'億人');
  await reload(page,);await page.waitForFunction(()=>document.querySelector('#rail-annual').getAttribute('aria-pressed')==='true'&&document.querySelector('#rail-value').textContent!=='—');
  await noOverflow(page);await page.screenshot({path:path.join(output,'national-'+width+'.png'),fullPage:true});
  assert.deepEqual(errors,[]);await context.close();console.log('Transport E2E passed: '+width+'px');
 }
 const page=await browser.newPage();await page.route('**/data/transport/usage.json',route=>route.fulfill({status:503,body:'unavailable'}));
 await goto(page,base+'/transport/?tab=national');await page.locator('#load-error').waitFor({state:'visible'});assert((await page.locator('#load-error').textContent()).includes('読み込めません'));await page.close();
 console.log('Transport E2E passed: explicit data failure; screenshots '+output);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
