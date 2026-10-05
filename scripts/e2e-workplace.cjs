const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.E2E_BASE_URL || 'https://datlume.com';
const root = process.cwd();
const samples = [];
for (const folder of ['listed-companies','company-registry']) {
  const items = Object.values(Object.assign({}, ...fs.readdirSync(path.join(root,'public/data',folder,'details')).filter(n=>n.endsWith('.json')).map(n=>JSON.parse(fs.readFileSync(path.join(root,'public/data',folder,'details',n),'utf8')).c)));
  const scored = items.filter(x=>x.workplace).sort((a,b)=> {
    const score = x => Object.keys(x.workplace.metrics).length + (Object.keys(x.workplace.hiring).length?10:0) + Object.values(x.workplace.metrics).filter(m=>m.note).length;
    return score(b)-score(a);
  });
  const route = item => folder==='listed-companies'?'/listed-companies/'+item.company.securityCode+'/':'/unlisted-companies/'+item.corporateNumber+'/';
  samples.push({route:route(scored[0]),workplace:scored[0].workplace});
  const zero = scored.find(x=>Object.values(x.workplace.metrics).some(m=>m.value===0));
  if (zero) samples.push({route:route(zero),workplace:zero.workplace});
  const missing = items.find(x=>!x.workplace);
  samples.push({route:route(missing),workplace:null});
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  let checks=0;
  try {
    for (const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
      const context=await browser.newContext({viewport});
      const page=await context.newPage();
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      for (const sample of samples) {
        const response=await page.goto(base+sample.route,{waitUntil:'networkidle'});
        assert.equal(response.status(),200,sample.route);
        const panel=page.locator('.workplace-panel');
        assert.equal(await panel.count(),sample.workplace?1:0,sample.route+' panel presence');
        if (sample.workplace) {
          assert.equal(await panel.getAttribute('data-corporate-number'),sample.workplace.corporateNumber);
          assert.equal(await panel.locator('.workplace-metric').count(),Object.keys(sample.workplace.metrics).length);
          for (const [key,m] of Object.entries(sample.workplace.metrics)) {
            const card=panel.locator('[data-metric-key="'+key+'"]');
            assert.equal((await card.locator('.workplace-value').textContent()).trim(),m.display,sample.route+' '+key);
            if(m.scope)assert((await card.textContent()).includes(m.scope.replace(/^\d+:/,'')));
            checks++;
          }
          assert.equal(await panel.locator('a').first().getAttribute('href'),sample.workplace.sourceUrl);
          const notes=panel.locator('.workplace-notes');
          if(await notes.count()) {
            await notes.locator('summary').click();
            for(const m of Object.values(sample.workplace.metrics))if(m.note)assert((await notes.textContent()).includes(m.note));
            assert(await notes.evaluate(el=>el.open));
            await notes.locator('summary').click();
          }
          for(const [key,h] of Object.entries(sample.workplace.hiring))for(const field of ['hires','leavers'])if(h[field]) {
            assert.deepEqual(await panel.locator('[data-hiring-key="'+key+'-'+field+'"] td').allTextContents(),h[field].map(v=>v.display));
            assert(await panel.locator(".workplace-table thead").first().isVisible(),sample.route+" cohort headers hidden");
            assert.deepEqual(await panel.locator(".workplace-table thead").first().locator("th").allTextContents(),["項目","前年度","2年度前","3年度前"]);
            const pseudo=await panel.locator(".workplace-table td").first().evaluate(el=>getComputedStyle(el,"::before").content);
            assert(["none","normal"].includes(pseudo),sample.route+" procurement label on hiring table");
            checks++;
          }
          const dir=path.join(root,'tmp/workplace-screens');fs.mkdirSync(dir,{recursive:true});
          await panel.screenshot({path:path.join(dir,name+'-'+sample.workplace.corporateNumber+'.png')});
        }
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),sample.route+' overflow');
        checks+=3;
      }
      await page.goto(base+'/unlisted-companies/',{waitUntil:'networkidle'});
      const index=JSON.parse(fs.readFileSync(path.join(root,'public/data/company-registry/unlisted-index.json'),'utf8')).records;
      await page.locator('#workplace-filter').selectOption('yes');
      const expected=index.filter(x=>x.hasWorkplace).length;
      await page.waitForFunction(n=>document.querySelector('#result-count')?.textContent===n.toLocaleString('ja-JP')+'社',expected);
      assert(await page.locator('.company-card').count()>0);
      const card=page.locator('.company-card').first();
      assert((await card.textContent()).includes('働き方データあり'));
      await card.click();await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('.workplace-panel').count(),1);
      assert.deepEqual(errors,[]);
      checks+=4;
      await context.close();
    }
    console.log(JSON.stringify({base,checks,samples:samples.map(x=>x.route),failures:0}));
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
