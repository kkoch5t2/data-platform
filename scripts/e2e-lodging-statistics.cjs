const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const data=JSON.parse(fs.readFileSync('public/data/lodging-statistics.json'));
const base=process.env.E2E_BASE_URL||'https://datlume.com';
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const [name,viewport] of [['desktop',{width:1440,height:900}],['mobile',{width:390,height:844}]]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   const response=await page.goto(base+'/regional/stays/',{waitUntil:'networkidle'});
   assert.equal(response.status(),200);
   assert((await page.title()).includes('宿泊旅行統計'));
   const latest=data.months.at(-1),tokyo=data.records.find(r=>r.prefecture==='東京都').values.at(-1);
   assert((await page.locator('body').innerText()).includes(latest.slice(0,4)+'年'+Number(latest.slice(5))+'月'));
   assert((await page.locator('#a-value').innerText()).includes(tokyo[0].toLocaleString('ja-JP')));
   await page.selectOption('#compare','北海道');
   assert((await page.locator('#b-value').innerText()).includes(data.records[1].values.at(-1)[0].toLocaleString('ja-JP')));
   await page.selectOption('#metric','foreignShare');
   assert((await page.locator('#a-value').innerText()).includes('%'));
   await page.selectOption('#period','all');
   assert(new URL(page.url()).searchParams.get('period')==='all');
   await page.reload({waitUntil:'networkidle'});
   assert.equal(await page.locator('#compare').inputValue(),'北海道');
   assert.equal(await page.locator('#metric').inputValue(),'foreignShare');
   assert.equal(await page.locator('#period').inputValue(),'all');
   assert.equal(await page.locator('#ranking canvas').count(),1);
   assert.equal(errors.length,0,errors.join('; '));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),'horizontal overflow '+name);
   const dir=path.join('tmp','lodging-statistics-screens');fs.mkdirSync(dir,{recursive:true});
   await page.screenshot({path:path.join(dir,name+'.png'),fullPage:true});
   await context.close();
  }
  console.log('lodging statistics PC/mobile E2E passed: '+base);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
