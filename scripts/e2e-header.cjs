const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {goto}=require('./e2e-navigation.cjs');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:8790';
const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):[path.join(d,e.name)]);
const built=walk('dist').filter(p=>p.endsWith('/index.html')).map(p=>'/'+p.slice(5,-10));
const routes=[];
for(const file of walk('src/pages').filter(p=>p.endsWith('.astro'))){
 let template='/'+file.slice(10).replace(/index\.astro$/, '').replace(/\.astro$/,'/');
 if(template==='/404/')continue;
 const pattern=new RegExp('^'+template.replace(/[.*+?^${}()|\\]/g,'\\$&').replace(/\[[^\]]+\]/g,'[^/]+')+'$');
 const route=built.find(r=>pattern.test(r));if(route)routes.push(route);
}
routes.push('/listed-companies/7203/','/procurement/companies/co_f96b284bc087/');
const unlisted=JSON.parse(fs.readFileSync('public/data/company-registry/unlisted-index.json')).records.find(r=>/^\d{13}$/.test(r.corporateNumber));
routes.push('/unlisted-companies/'+unlisted.corporateNumber+'/');
// Check every generated page as well as representative browser routes.
for(const file of walk('dist').filter(p=>p.endsWith('.html'))){
 const html=fs.readFileSync(file,'utf8');
 assert.equal((html.match(/class="datlume-nav"/g)||[]).length,1,file+' shared navigation count');
 assert(html.includes('/brand/navigation.css?v=20261011-2'),file+' navigation stylesheet');
 assert(html.includes('/brand/navigation.js?v=20261011-2'),file+' navigation dismissal script');
}
(async()=>{
 const browser=await chromium.launch({headless:true});let checks=0;const failures=[];let expected;
 fs.mkdirSync('tmp/header-qa',{recursive:true});
 for(const width of [1440,390,320]){
  const page=await browser.newPage({viewport:{width,height:900}});
  for(const route of [...new Set(routes)])try{
   const response=await goto(page,base+encodeURI(route),{waitUntil:'domcontentloaded',timeout:60000});assert.equal(response.status(),200);
   const nav=page.locator('header .datlume-nav');assert.equal(await nav.count(),1);
   await page.waitForFunction(()=>getComputedStyle(document.querySelector('.datlume-menu-panel')).position==='absolute');
   const links=await nav.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
   if(!expected)expected=links;assert.deepEqual(links,expected,'site navigation differs');assert(links.includes('/agriculture/')&&links.includes('/transport/')&&links.includes('/topics/'));
   const actions=nav.locator('.datlume-nav-actions');assert.equal(await actions.locator(':scope > *').count(),2);
   assert.equal(await actions.locator(':scope > details').count(),2);
   assert.equal(await actions.locator(':scope > a').count(),0,'topic must not be in top-level navigation');
   assert.equal(await nav.locator('.datlume-data-panel a[href="/topics/"]').count(),1);
   for(const summary of await nav.locator('summary').all()){
    const aligned=await summary.evaluate(el=>{
     const a=el.getBoundingClientRect(),b=el.querySelector('.datlume-chevron').getBoundingClientRect();
     return Math.abs((a.top+a.height/2)-(b.top+b.height/2))<=1.5;
    });
    assert(aligned,'chevron vertical alignment');
   }
   const titleSize=await page.locator('h1').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize));assert(titleSize<=(width<=600?(route==='/'?30:28):(route==='/'?44:40)),'title too large');
   const menu=nav.locator('details').first();await menu.locator('summary').click();assert(await menu.evaluate(e=>e.open));
   const panel=menu.locator('.datlume-menu-panel');
   assert(await panel.locator('a[href="/topics/"]').isVisible(),'topic link should be discoverable in Data menu');
   assert(await menu.locator('.datlume-chevron').evaluate(e=>getComputedStyle(e).stroke!=='none'),'chevron must be rendered');const box=await panel.boundingBox();const panelScroll=await panel.evaluate(e=>({w:e.scrollWidth,c:e.clientWidth}));assert(panelScroll.w<=panelScroll.c+1,'panel content overflow');assert(box.x>=-1&&box.x+box.width<=width+1,'open panel overflow');
   assert(await panel.locator('a').last().isVisible());
   await page.keyboard.press('Escape');assert.equal(await menu.evaluate(e=>e.open),false);assert(await menu.locator('summary').evaluate(e=>e===document.activeElement));
   await menu.locator('summary').click();const info=nav.locator('details').last();await info.locator('summary').click();await page.waitForTimeout(50);assert.equal(await menu.evaluate(e=>e.open),false);assert(await info.evaluate(e=>e.open));
   await page.mouse.click(2,850);assert.equal(await info.evaluate(e=>e.open),false);
   const nbox=await nav.boundingBox();const hbox=await page.locator('h1').first().boundingBox();assert(hbox.y>=nbox.y+nbox.height,'navigation overlaps title');
   assert(await nav.evaluate(e=>e.getBoundingClientRect().right<=innerWidth+1),'nav overflow');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow');
   if(['/', '/procurement/','/agriculture/','/listed-companies/7203/'].includes(route)){await page.screenshot({path:'tmp/header-qa/'+width+'-'+(route.replaceAll('/','_')||'home')+'.png'});await menu.locator('summary').click();await page.screenshot({path:'tmp/header-qa/'+width+'-'+(route.replaceAll('/','_')||'home')+'-open.png'});await page.keyboard.press('Escape');}
   checks++;console.log('PASS',width,route);
  }catch(e){failures.push(width+' '+route+' '+e.message);console.log('FAIL',failures.at(-1))}
  await page.close();
 }
 await browser.close();console.log(JSON.stringify({checks,failures},null,2));if(failures.length)process.exit(1);
})();
