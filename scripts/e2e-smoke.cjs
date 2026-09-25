const { chromium } = require('playwright');
const base='https://datlume.com';
const routes=['/procurement/','/realestate/','/regional/','/employment-economy/','/business-industry/','/economy-prices/','/energy/'];
(async()=>{const browser=await chromium.launch({headless:true});let failures=[];
for(const vp of [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}]){
 const ctx=await browser.newContext({viewport:{width:vp.width,height:vp.height}});
 for(const route of routes){const page=await ctx.newPage();const errs=[],bad=[];
 page.on('pageerror',e=>errs.push(e.message)); page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('404'))errs.push(m.text())});
 page.on('response',r=>{if(r.status()>=400&&!r.url().includes('disaportaldata.gsi.go.jp/raster/'))bad.push(r.status()+' '+r.url())});
 try{const res=await page.goto(base+route,{waitUntil:'networkidle',timeout:60000});await page.waitForTimeout(500);
 const o=await page.evaluate(()=>[document.documentElement.scrollWidth,document.documentElement.clientWidth]);
 const tabs=page.locator('button.tab:visible');for(let i=0;i<await tabs.count();i++){await tabs.nth(i).click();await page.waitForTimeout(120)}
 const selects=page.locator('select:visible');for(let i=0;i<await selects.count();i++){const s=selects.nth(i),n=await s.locator('option').count();if(n>1){await s.selectOption({index:1});await page.waitForTimeout(80)}}
 const loading=await page.locator('text=/読み込み中|読込中/').count();
 if(o[0]>o[1]+2)failures.push(vp.name+' '+route+' overflow '+o.join('>'));
 if(errs.length)failures.push(vp.name+' '+route+' JS '+[...new Set(errs)].slice(0,2).join('|'));
 if(bad.length)failures.push(vp.name+' '+route+' HTTP '+[...new Set(bad)].slice(0,2).join('|'));
 console.log(vp.name,route,'HTTP',res.status(),'tabs',await tabs.count(),'selects',await selects.count(),'loading',loading,'overflow',o[0]-o[1],'errors',errs.length,'bad',bad.length);
 }catch(e){failures.push(vp.name+' '+route+' FATAL '+e.message)}await page.close()}
 await ctx.close()}
await browser.close();console.log('FAILURES',failures.length);failures.forEach(x=>console.log('FAIL',x));process.exit(failures.length?1:0)})();