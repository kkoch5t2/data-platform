const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const {goto}=require('./e2e-navigation.cjs');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:4326';
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAADIElEQVR4nO3UQQEAEADAQLTQT2xhxPDYXYK9Nve5ZwBJ63cA8I8BQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQJgBQNgDXbADvQXJgk8AAAAASUVORK5CYII=','base64');
(async()=>{
 const browser=await chromium.launch({headless:true});let checks=0;
 try{for(const [name,width] of [['desktop',1440],['mobile',390],['small',320]]){
  const context=await browser.newContext({viewport:{width,height:960}}),page=await context.newPage(),errors=[];let mode=404,requests=0;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://tiles.openfreemap.org/styles/liberty',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#eef3f8'}}]})}));
  await page.route('https://disaportaldata.gsi.go.jp/raster/**',r=>{
   requests++;if(mode==='abort')return r.abort('failed');
   return r.fulfill({status:mode==='invalid'?200:mode,headers:{'access-control-allow-origin':'*'},
    contentType:mode===200?'image/png':'text/plain',body:mode===200?png:'unavailable'});
  });
  await goto(page,base+'/realestate/');
  await page.waitForFunction(()=>document.querySelector('#hazard-status-flood').dataset.state==='missing');
  assert((await page.locator('#hazard-status-flood').textContent()).includes('配信画像がありません'));
  assert.equal(await page.locator('#hazard-status-tsunami').getAttribute('data-state'),'off');
  for(const [value,expected] of [[200,'loaded'],[503,'failed'],['abort','failed'],['invalid','failed'],[404,'missing']]){
   mode=value;const before=requests;await page.locator('#hazard-retry').click();
   await page.waitForFunction(expected=>document.querySelector('#hazard-status-flood').dataset.state===expected,expected);
   assert(requests>before);assert((await page.locator('#hazard-status-flood').textContent()).includes(expected==='failed'?'失敗':expected==='loaded'?'画像取得済み':'配信データなし'));checks+=2;
  }
  if(width<560)await page.locator('#filters-toggle').click();
  await page.locator('#layer-flood').uncheck();assert.equal(await page.locator('#hazard-status-flood').getAttribute('data-state'),'off');
  const before=requests;await page.locator('#hazard-retry').click();await page.waitForTimeout(150);assert.equal(requests,before);
  await page.locator('#layer-tsunami').check();
  await page.waitForFunction(()=>document.querySelector('#hazard-status-tsunami').dataset.state==='missing');
  await page.locator('#layer-sediment').check();
  await page.waitForFunction(()=>document.querySelector('#hazard-status-sediment').dataset.state==='missing');
  await page.evaluate(()=>window.__DATLUME_MAP__.jumpTo({center:[139.75,35.7],zoom:10}));
  await page.waitForFunction(()=>document.querySelector('#hazard-status-tsunami').dataset.state==='missing');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  assert.deepEqual(errors,[]);checks+=8;
  fs.mkdirSync('tmp/hazard-screens',{recursive:true});await page.locator('.hazard-status').screenshot({path:'tmp/hazard-screens/'+name+'.png'});
  await context.close();
 }console.log(JSON.stringify({base,checks,failures:0}));}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
