const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.E2E_BASE_URL || 'https://datlume.com';
const root = process.cwd();
function entries(area) {
  return Object.values(Object.assign({}, ...fs.readdirSync(path.join(root,'public/data',area,'details'))
    .filter(name=>name.endsWith('.json'))
    .map(name=>JSON.parse(fs.readFileSync(path.join(root,'public/data',area,'details',name))).c)));
}
const samples=[];
for(const area of ['listed-companies','company-registry']){
  const items=entries(area);
  const route=item=>area==='listed-companies'?'/listed-companies/'+item.company.securityCode+'/':'/unlisted-companies/'+item.corporateNumber+'/';
  const full=items.filter(item=>item.activity?.subsidies && item.activity?.patents?.recent?.length>5).sort((a,b)=>b.activity.patents.recent.length-a.activity.patents.recent.length)[0];
  const missing=items.find(item=>!item.activity);
  assert(full && missing,area+' sample availability');
  samples.push({route:route(full),activity:full.activity},{route:route(missing),activity:null});
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  let checks=0;
  try{
    for(const [name,viewport] of [['desktop',{width:1440,height:900}],['mobile',{width:390,height:844}]]){
      const context=await browser.newContext({viewport});
      const page=await context.newPage();
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      for(const sample of samples){
        const response=await page.goto(base+sample.route,{waitUntil:'networkidle'});
        assert.equal(response.status(),200,sample.route);
        const panels=page.locator('.activity-panel');
        assert.equal(await panels.count(),sample.activity?2:0,sample.route);
        if(sample.activity){
          const [subsidies,patents]=sample.activity.subsidies? [sample.activity.subsidies,sample.activity.patents]:[];
          const subsidyPanel=panels.first(),patentPanel=panels.last();
          assert((await subsidyPanel.textContent()).includes(subsidies.count.toLocaleString('ja-JP')+'件'));
          assert((await patentPanel.textContent()).includes(patents.count.toLocaleString('ja-JP')+'件'));
          assert.equal(await subsidyPanel.locator('li').count(),subsidies.recent.length);
          assert.equal(await patentPanel.locator(':scope > ul li').count(),Math.min(5,patents.recent.length));
          const more=patentPanel.locator('details.activity-more');
          assert.equal(await more.count(),patents.recent.length>5?1:0);
          if(patents.recent.length>5){await more.locator('summary').click();assert(await more.evaluate(el=>el.open));}
          assert.equal(await patentPanel.locator('li').count(),patents.recent.length);
          assert((await subsidyPanel.textContent()).includes(subsidies.recent[0].name));
          assert((await patentPanel.textContent()).includes(patents.recent[0].registration));
          assert((await subsidyPanel.textContent()).includes(subsidies.sourceDate));
          assert((await patentPanel.textContent()).includes(patents.sourceDate));
          assert.equal(await subsidyPanel.locator('a').first().getAttribute('href'),'https://info.gbiz.go.jp/hojin/DownloadTop');
          const dir=path.join(root,'tmp/gbiz-activity-screens');fs.mkdirSync(dir,{recursive:true});
          await patentPanel.screenshot({path:path.join(dir,name+'-'+sample.route.split('/').filter(Boolean).join('-')+'-patents.png')});
          checks+=9;
        }
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),sample.route+' horizontal overflow');
        checks+=2;
      }
      assert.deepEqual(errors,[]);
      await context.close();
    }
    console.log(JSON.stringify({base,checks,samples:samples.map(x=>x.route),failures:0}));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
