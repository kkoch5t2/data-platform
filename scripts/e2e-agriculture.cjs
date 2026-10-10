const { chromium } = require('playwright');
const fs = require('node:fs');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:9876';
const data = JSON.parse(fs.readFileSync('public/data/agriculture-output.json','utf8'));
const item = name => data.products.findIndex(x => x.name === name);
const number = text => Number(text.replace(/[^\d]/g,''));
(async()=>{
  const browser=await chromium.launch({headless:true});
  const failures=[];
  try{
    for(const [label,width,height] of [['desktop',1440,960],['mobile',390,844]]){
      const page=await browser.newPage({viewport:{width,height}});
      page.on('pageerror',e=>failures.push(label+' JS: '+e.message));
      const response=await page.goto(base+'/agriculture/',{waitUntil:'networkidle'});
      if(response.status()!==200)failures.push(label+' HTTP '+response.status());
      await page.waitForFunction(()=>document.querySelectorAll('#ranking .rank-row').length===15,{timeout:12000});
      const rice=data.records.filter(r=>Number.isInteger(r.values[item('米')])).sort((a,b)=>b.values[item('米')]-a.values[item('米')]||a.code.localeCompare(b.code))[0];
      const first=await page.locator('.rank-row').first().textContent();
      if(!first.includes(rice.city)||!first.includes(rice.values[item('米')].toLocaleString('ja-JP')))failures.push(label+' rice ranking does not match source');
      await page.locator('[data-item="トマト"]').click();
      const tomato=data.records.filter(r=>Number.isInteger(r.values[item('トマト')])).sort((a,b)=>b.values[item('トマト')]-a.values[item('トマト')]||a.code.localeCompare(b.code))[0];
      if(!(await page.locator('.rank-row').first().textContent()).includes(tomato.city))failures.push(label+' tomato ranking does not match source');
      await page.locator('#prefecture').selectOption('熊本県');
      if((await page.locator('.rank-row').first().textContent()).includes('愛知県'))failures.push(label+' prefecture filter failed');
      await page.locator('#city-search').fill('八代');
      if(await page.locator('.rank-row').count()!==1)failures.push(label+' municipality search failed');
      await page.locator('.rank-row').first().click();
      if(!(await page.locator('#detail').textContent()).includes('八代市'))failures.push(label+' municipality detail failed');
      await page.locator('#city-search').fill('');
      await page.locator('#prefecture').selectOption('');
      if(!(await page.locator('#more').isVisible()))failures.push(label+' show more missing');
      await page.locator('#more').click();
      if(await page.locator('.rank-row').count()!==30)failures.push(label+' show more failed');
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
      if(overflow>1)failures.push(label+' horizontal overflow '+overflow);
      await page.screenshot({path:'tmp/agriculture-'+label+'.png',fullPage:true});
      await page.close();
    }
  }finally{await browser.close()}
  if(failures.length){console.error(failures.join('\n'));process.exit(1)}
  console.log('agriculture desktop/mobile operations PASS: rankings, filters, details, more, overflow');
})();
