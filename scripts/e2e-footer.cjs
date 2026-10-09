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
(async()=>{
 const browser=await chromium.launch({headless:true});let checks=0;const failures=[];
 fs.mkdirSync('tmp/footer-qa',{recursive:true});
 for(const width of [1440,390,320]){
  const page=await browser.newPage({viewport:{width,height:900}});
  for(const route of [...new Set(routes)])try{
   const response=await goto(page,base+encodeURI(route),{waitUntil:'domcontentloaded',timeout:60000});assert.equal(response.status(),200);
   const footer=page.locator('footer.datlume-footer');assert.equal(await footer.count(),1);
   await footer.scrollIntoViewIfNeeded();
   await page.waitForFunction(()=>{const f=document.querySelector('.datlume-footer');return f&&getComputedStyle(f).paddingTop==='28px'&&[...f.querySelectorAll('img')].every(i=>i.complete&&i.naturalWidth>0)});
   const state=await footer.evaluate(f=>{const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,right:r.right,y:r.y,bottom:r.bottom}};return {width:innerWidth,inner:rect(f.querySelector('.datlume-footer-inner')),description:rect(f.querySelector('.datlume-footer-description')),nav:rect(f.querySelector('nav')),links:[...f.querySelectorAll('nav a')].map(a=>({href:a.getAttribute('href'),...rect(a)})),border:getComputedStyle(f).borderTopWidth}});
   assert.equal(state.border,'1px');assert.equal(state.links.length,2);
   assert.deepEqual(state.links.map(a=>a.href),['https://github.com/kkoch5t2/data-platform','/privacy/']);
   assert(state.inner.x>=0&&state.inner.right<=width+1);
   for(const link of state.links)assert(link.x>=state.inner.x-1&&link.right<=state.inner.right+1,'footer link overflow');
   if(width<=520)assert(state.nav.y>=state.description.bottom+10,'mobile description and navigation overlap');
   const related=footer.locator('.datlume-related-card');assert.equal(await related.count(),1);assert.equal(await related.getAttribute('href'),'https://utility-tools-jp.com/');
   assert(await related.locator('strong').textContent());assert(await related.locator('small').textContent());
   const box=await related.boundingBox();assert(box.x>=state.inner.x-1&&box.x+box.width<=state.inner.right+1,'related card overflow');assert(box.height>=60,'related card tap area too small');assert(box.y>=state.nav.bottom,'related card overlaps navigation');
   await related.focus();assert.equal(await related.evaluate(e=>e===document.activeElement),true);

   if(['/', '/regional/','/realestate/','/listed-companies/7203/'].includes(route))await footer.screenshot({path:'tmp/footer-qa/'+width+'-'+(route.replaceAll('/','_')||'home')+'.png'});
   checks++;console.log('PASS',width,route);
  }catch(e){failures.push(width+' '+route+' '+e.message);console.log('FAIL',failures.at(-1))}
  await page.close();
 }
 await browser.close();console.log(JSON.stringify({checks,failures},null,2));if(failures.length)process.exit(1);
})();
