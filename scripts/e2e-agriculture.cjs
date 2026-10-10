const { chromium } = require('playwright');
const fs = require('node:fs');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:9876';
const data = JSON.parse(fs.readFileSync('public/data/agriculture-output.json','utf8'));
const item = name => data.products.findIndex(x => x.name === name);
const sort = (name,pref='') => data.records.filter(r=>typeof r.values[item(name)]==='number'&&(!pref||r.prefecture===pref)).sort((a,b)=>b.values[item(name)]-a.values[item(name)]||a.code.localeCompare(b.code));
const value = n => n===0?'千万円未満':new Intl.NumberFormat('ja-JP',{maximumFractionDigits:1}).format(n/10)+'億円';
(async()=>{
 const browser=await chromium.launch({headless:true});
 const failures=[];fs.mkdirSync('tmp/agriculture-ui-screens',{recursive:true});
 const check=(ok,msg)=>{if(!ok)failures.push(msg)};
 try{
  for(const [label,width,height] of [['desktop',1440,960],['mobile',390,844],['small-mobile',320,740]]){
   const page=await browser.newPage({viewport:{width,height}});
   page.on('pageerror',e=>failures.push(label+' JS: '+e.message));
   page.on('console',m=>{if(m.type()==='error')failures.push(label+' console: '+m.text())});
   const response=await page.goto(base+'/agriculture/',{waitUntil:'networkidle'});
   check(response.status()===200,label+' HTTP');
   await page.waitForFunction(()=>document.querySelectorAll('#ranking .rank-row').length===15,{timeout:15000});
   await page.locator('#ranking-chart canvas').waitFor();
   const rice=sort('米')[0];
   check((await page.locator('.rank-row').first().textContent()).includes(rice.city),label+' rice leader');
   check((await page.locator('.rank-row .amount').first().textContent())===value(rice.values[item('米')]),label+' yen conversion');
   check((await page.locator('#public-count').textContent())===sort('米').length.toLocaleString('ja-JP')+'市町村',label+' count');
   check((await page.locator('#leader-amount').textContent())===value(rice.values[item('米')]),label+' leader metric');
   const css=await page.locator('.rank-row').first().evaluate(el=>({display:getComputedStyle(el).display,amount:getComputedStyle(el.querySelector('.amount')).fontWeight}));
   check(css.display==='grid'&&Number(css.amount)>=700,label+' dynamic CSS missing');
   for(const name of ['米','トマト','いちご','りんご','生乳','農業産出額']){
    const card=page.locator('[data-item="'+name+'"]');
    check((await card.textContent()).includes(sort(name)[0].city),label+' card source '+name);
   }
   await page.screenshot({path:'tmp/agriculture-ui-screens/'+label+'-initial.png',fullPage:true});
   // Use the actual chart canvas: grid bounds are derived from rendered bar labels.
   const canvas=page.locator('#ranking-chart canvas');
   const box=await canvas.boundingBox();
   await canvas.click({position:{x:Math.min(box.width-75,box.width*0.5),y:57}});
   const second=sort('米')[1];
   check((await page.locator('#detail .detail-title').textContent()).includes(second.city),label+' chart second bar click');
   check((await page.locator('.rank-row[aria-pressed=true]').getAttribute('data-code'))===second.code,label+' chart/list selection sync');
   const url=page.url();await page.goto(url,{waitUntil:'networkidle'});
   await page.waitForFunction(()=>document.querySelectorAll('#ranking .rank-row').length===15);
   check((await page.locator('#detail .detail-title').textContent()).includes(second.city),label+' URL city restore');
   await page.locator('[data-item="トマト"]').click();
   check((await page.locator('.rank-row').first().textContent()).includes(sort('トマト')[0].city),label+' tomato leader');
   await page.locator('#prefecture').selectOption('熊本県');
   check((await page.locator('#public-count').textContent())===sort('トマト','熊本県').length.toLocaleString('ja-JP')+'市町村',label+' prefecture count');
   await page.locator('#city-search').fill('八代');
   check(await page.locator('.rank-row').count()===1,label+' search');
   await page.locator('.rank-row').click();
   const yatsushiro=data.records.find(r=>r.city==='八代市'&&r.prefecture==='熊本県');
   check((await page.locator('#detail .detail-title').textContent()).includes('八代市'),label+' detail city');
   check((await page.locator('#detail .picked').textContent())===value(yatsushiro.values[item('トマト')]),label+' detail selected amount');
   const detailRows=await page.locator('#detail .product-row').evaluateAll(es=>es.map(e=>({name:e.dataset.product,value:Number(e.dataset.value),text:e.querySelector('b').textContent,width:parseFloat(e.querySelector('.fill').style.width)})));
   const expected=data.products.map((p,i)=>({p,v:yatsushiro.values[i]})).filter(x=>!x.p.aggregate&&typeof x.v==='number'&&x.v>0).sort((a,b)=>b.v-a.v).slice(0,8);
   check(detailRows.length===expected.length,label+' detail count');
   detailRows.forEach((r,i)=>check(r.name===expected[i].p.name&&r.value===expected[i].v&&r.text===value(r.value)&&Math.abs(r.width-r.value/expected[0].v*100)<0.01,label+' detail bar source '+i));
   await page.screenshot({path:'tmp/agriculture-ui-screens/'+label+'-selected.png',fullPage:true});
   await page.locator('#city-search').fill('存在しない市町村xyz');
   check(await page.locator('.rank-row').count()===0,label+' empty rows');
   check(!(await page.locator('#detail').textContent()).includes('八代市'),label+' stale detail after empty');
   check((await page.locator('#ranking-chart').getAttribute('aria-label')).includes('上位0'),label+' stale chart after empty');
   await page.locator('#city-search').fill('');await page.locator('#prefecture').selectOption('');
   await page.locator('#more').click();check(await page.locator('.rank-row').count()===30,label+' more');
   // All 70 selectable fields: top-10 labels and amounts must correspond to the source.
   for(let i=0;i<data.products.length;i++){
    await page.locator('#item').selectOption(String(i));
    const expectedRows=sort(data.products[i].name).slice(0,15);
    const actual=await page.locator('.rank-row').evaluateAll(es=>es.map(e=>({code:e.dataset.code,value:Number(e.dataset.value),amount:e.querySelector('.amount').textContent})));
    check(JSON.stringify(actual)===JSON.stringify(expectedRows.map(r=>({code:r.code,value:r.values[i],amount:value(r.values[i])}))),label+' all-item ranking '+data.products[i].name);
    const aria=await page.locator('#ranking-chart').getAttribute('aria-label');
    check(expectedRows.slice(0,10).every(r=>aria.includes(r.city+' '+value(r.values[i]))),label+' chart source '+data.products[i].name);
   }
   check(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)<=1,label+' overflow');
   await page.close();
  }
  const errorPage=await browser.newPage({viewport:{width:390,height:844}});
  await errorPage.route('**/data/agriculture-output.json',r=>r.fulfill({status:503,body:'unavailable'}));
  await errorPage.goto(base+'/agriculture/',{waitUntil:'networkidle'});
  check(await errorPage.locator('#load-error').isVisible(),'fetch failure message');
  check(await errorPage.locator('#item').isDisabled(),'fetch failure disabled filter');
  await errorPage.locator('[data-item="米"]').click();
  check(await errorPage.locator('.rank-row').count()===0,'fetch failure stale ranking');
  await errorPage.close();
 }finally{await browser.close()}
 if(failures.length){console.error(failures.join('\n'));process.exit(1)}
 console.log('agriculture UI PASS: PC/390px/320px, 70 items source match, chart clicks, detail bars, filters, yen units, CSS, URL, empty/error states');
})().catch(e=>{console.error(e);process.exit(1)});
