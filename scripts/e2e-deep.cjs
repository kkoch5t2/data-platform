const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.E2E_BASE_URL || 'https://datlume.com';
const dist = path.join(process.cwd(), 'dist');
const shotRoot = path.join(process.cwd(), 'tmp', 'e2e-screens');
const viewports = [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}];

function walk(dir, out=[]) {
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    const file=path.join(dir,name), st=fs.statSync(file);
    if (st.isDirectory()) walk(file,out);
    else if (name==='index.html') {
      let rel=path.relative(dist,file).split(path.sep).join('/');
      out.push(rel==='index.html' ? '/' : '/'+rel.slice(0,-'index.html'.length));
    }
  }
  return out;
}
const builtRoutes=walk(dist).sort((a,b)=>a.localeCompare(b,'ja'));
const staticRoutes=['/','/about-data/','/analytics/','/procurement/','/realestate/','/regional/','/employment-economy/','/business-industry/','/economy-prices/','/energy/'];
const families=[
  ['proc-company', /^\/procurement\/companies\/co_[^/]+\/$/],
  ['proc-market', /^\/procurement\/markets\/(?!index)[^/]+\/$/],
  ['proc-org', /^\/procurement\/organizations\/org_[^/]+\/$/],
  ['proc-tech', /^\/procurement\/technologies\/(?!index)[^/]+\/$/],
  ['proc-year', /^\/procurement\/years\/2026\/$/],
  ['proc-year-market', /^\/procurement\/years\/2026\/markets\/[^/]+\/$/],
  ['proc-year-tech', /^\/procurement\/years\/2026\/technologies\/[^/]+\/$/],
  ['business-pref', /^\/business-industry\/prefectures\/北海道\/$/],
  ['business-indicator', /^\/business-industry\/indicators\/[^/]+\/$/],
  ['economy-pref', /^\/economy-prices\/prefectures\/北海道\/$/],
  ['economy-indicator', /^\/economy-prices\/indicators\/[^/]+\/$/],
  ['employment-pref', /^\/employment-economy\/prefectures\/北海道\/$/],
  ['employment-indicator', /^\/employment-economy\/indicators\/[^/]+\/$/],
  ['energy-pref', /^\/energy\/prefectures\/北海道\/$/],
  ['energy-indicator', /^\/energy\/indicators\/[^/]+\/$/],
  ['regional-pref', /^\/regional\/prefectures\/北海道\/$/],
  ['regional-indicator', /^\/regional\/indicators\/[^/]+\/$/],
];
const routes=[...staticRoutes];
for (const [name,re] of families) {
  const hit=builtRoutes.find(r=>re.test(r));
  if (!hit) throw new Error('No built route for family '+name);
  routes.push(hit);
}
const uniqueRoutes=[...new Set(routes)];
const onlyRoutes=(process.env.E2E_ONLY||'').split(',').map(x=>x.trim()).filter(Boolean);
const activeRoutes=onlyRoutes.length?uniqueRoutes.filter(r=>onlyRoutes.includes(r)):uniqueRoutes;
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const unique = xs => [...new Set(xs)];
const safeRoute = r => (r==='/'?'home':r.replace(/^\//,'').replace(/\/$/,'').replace(/[^a-zA-Z0-9_-]+/g,'_')).slice(0,120);

async function exerciseVisibleSelects(page) {
  const selects=page.locator('select:visible');
  for (let i=0;i<await selects.count();i++) {
    const s=selects.nth(i), n=await s.locator('option').count();
    if (n<=1) continue;
    const current=await s.inputValue();
    const options=await s.locator('option').evaluateAll(os=>os.map(o=>o.value));
    const next=options.find(v=>v && v!==current) ?? options.find(v=>v!==current);
    if (next!==undefined) {
      await s.selectOption(next).catch(()=>{});
      await page.waitForTimeout(100);
    }
  }
}

async function checkRealestateMapPalette(page,label,failures) {
  await page.waitForFunction(()=>window.__DATLUME_MAP__?.getLayer?.('price-points'),{timeout:20000}).catch(()=>{});
  const basePalette=await page.evaluate(()=>{
    const m=window.__DATLUME_MAP__;
    return {
      paint:m?.getPaintProperty?.('price-points','circle-color'),
      cluster:m?.getPaintProperty?.('price-clusters','circle-color'),
      landLegend:[...document.querySelectorAll('#legend .dot')].map(el=>el.getAttribute('style')||'')
    };
  }).catch(()=>({}));
  await page.waitForFunction(()=>window.__DATLUME_MAP__?.getLayer?.('municipal-stat-points'),{timeout:20000}).catch(()=>{});
  await page.evaluate(()=>{
    const el=document.querySelector('#stat-layer');
    if(el){el.value='population';el.dispatchEvent(new Event('change',{bubbles:true}));}
  }).catch(()=>{});
  await page.waitForFunction(()=>{
    const p=window.__DATLUME_MAP__?.getPaintProperty?.('municipal-stat-points','circle-color');
    return JSON.stringify(p||[]).includes('#111827');
  },{timeout:5000}).catch(()=>{});
  const populationPalette=await page.evaluate(()=>{
    const m=window.__DATLUME_MAP__;
    return {
      paint:m?.getPaintProperty?.('municipal-stat-points','circle-color'),
      legend:[...document.querySelectorAll('#legend .dot')].map(el=>el.getAttribute('style')||'')
    };
  }).catch(()=>({}));
  const palette={...basePalette,population:populationPalette.paint,populationLegend:populationPalette.legend};
  const encoded=JSON.stringify(palette.paint||[]);
  if(!encoded.includes('#1769e0'))failures.push(label+' land-price points are not plain blue: '+encoded);
  if(palette.cluster!=='#1769e0')failures.push(label+' land-price cluster is not blue: '+palette.cluster);
  const landLegendText=(palette.landLegend||[]).join(' ');
  if(!landLegendText.includes('#1769e0'))failures.push(label+' land-price legend is not plain blue');
  const populationEncoded=JSON.stringify(palette.population||[]);
  for(const color of ['#e5e7eb','#9ca3af','#4b5563','#111827']){
    if(!populationEncoded.includes(color))failures.push(label+' population palette missing '+color);
  }
  if(populationEncoded.includes('#1769e0'))failures.push(label+' population still overlaps land-price blue: '+populationEncoded);
  const populationLegendText=(palette.populationLegend||[]).join(' ');
  for(const color of ['#e5e7eb','#9ca3af','#4b5563','#111827']){
    if(!populationLegendText.includes(color))failures.push(label+' population legend missing '+color);
  }
  for(const [kind,colors] of [['single',['#ede9fe','#7c3aed']],['migration',['#c026d3','#16a34a']]]){
    await page.evaluate(k=>{const el=document.querySelector('#stat-layer');if(el){el.value=k;el.dispatchEvent(new Event('change',{bubbles:true}));}},kind).catch(()=>{});
    await page.waitForTimeout(120);
    const state=await page.evaluate(()=>({paint:window.__DATLUME_MAP__?.getPaintProperty?.('municipal-stat-points','circle-color'),legend:document.querySelector('#legend')?.textContent||''})).catch(()=>({}));
    const enc=JSON.stringify(state.paint||[]);
    for(const color of colors)if(!enc.includes(color))failures.push(label+' '+kind+' palette missing '+color);
    if(kind==='single'&&!String(state.legend||'').includes('単身世帯率'))failures.push(label+' single-household legend missing');
    if(kind==='migration'&&!String(state.legend||'').includes('人口移動'))failures.push(label+' migration legend missing');
  }
}

async function checkRegionalMunicipal(page,label,failures) {
  const load=page.locator('#municipal-load');
  if(!(await load.count())){failures.push(label+' municipal loader missing');return}
  await load.click();
  await page.waitForFunction(()=>!document.querySelector('#municipal-body')?.hidden&&document.querySelector('#municipal-status')?.textContent?.includes('市区町村'),{timeout:15000}).catch(()=>{});
  const initial=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(initial||'').includes('1,741市区町村')||!(initial||'').includes('2020年値'))failures.push(label+' municipal nationwide status invalid: '+initial);
  await page.selectOption('#municipal-pref','東京都').catch(()=>{});await page.selectOption('#municipal-metric','singleHouseholdRate').catch(()=>{});await page.waitForTimeout(150);
  const single=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(single||'').includes('東京都')||!(single||'').includes('単身世帯率')||!(single||'').includes('2020年値'))failures.push(label+' municipal single-household filter failed: '+single);
  await page.selectOption('#municipal-metric','netMigration').catch(()=>{});await page.waitForTimeout(150);
  const migration=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(migration||'').includes('転入超過・転出超過')||!(migration||'').includes('2024年値'))failures.push(label+' municipal migration filter failed: '+migration);
  if(!(await page.locator('#municipal-chart canvas').count()))failures.push(label+' municipal chart canvas missing');
}

async function checkEconomyPriceHistory(page,label,failures) {
  const tab=page.locator('[data-tab="history"]');
  if(!(await tab.count())){failures.push(label+' economy history tab missing');return}
  await tab.click();
  await page.waitForFunction(()=>document.querySelectorAll('#price-history-chart canvas').length>0,{timeout:15000}).catch(()=>{});
  const years=await page.evaluate(async()=>{const r=await fetch('/data/economy-prices-history.json');if(!r.ok)return[];return(await r.json()).years||[]}).catch(()=>[]);
  if(years.length!==13||Number(years[0])!==2013||Number(years.at(-1))!==2025)failures.push(label+' economy history coverage invalid: '+JSON.stringify(years));
  if(!(await page.locator('#price-history-chart canvas').count()))failures.push(label+' economy history chart canvas missing');
  const sub=(await page.locator('[data-panel="history"] .chart-sub').textContent().catch(()=>''))?.trim();
  if(!(sub||'').includes('2013〜2025年'))failures.push(label+' economy history period label invalid: '+sub);
}

async function checkEnergyCo2History(page,label,failures) {
  const tab=page.locator('[data-tab="consumption-history"]');
  if(!(await tab.count())){failures.push(label+' energy history tab missing');return}
  await tab.click();
  await page.waitForFunction(()=>document.querySelectorAll('#consumption-history-chart canvas').length>0,{timeout:15000}).catch(()=>{});
  const meta=await page.evaluate(async()=>{const r=await fetch('/data/energy-consumption-history.json');if(!r.ok)return{};const d=await r.json();return{years:d.years||[],fields:d.fields||[]}}).catch(()=>({}));
  if((meta.years||[]).length!==19||Number(meta.years?.[0])!==1990||Number(meta.years?.at(-1))!==2023)failures.push(label+' energy history coverage invalid: '+JSON.stringify(meta.years));
  if(!(meta.fields||[]).includes('finalCo2PerCapita'))failures.push(label+' CO2 history field missing');
  await page.selectOption('#consumption-history-metric','finalCo2PerCapita').catch(()=>{});await page.waitForTimeout(200);
  const title=(await page.locator('#consumption-history-title').textContent().catch(()=>''))?.trim();
  const note=(await page.locator('#consumption-history-note').textContent().catch(()=>''))?.trim();
  if(!(title||'').includes('CO₂排出量'))failures.push(label+' CO2 history title invalid: '+title);
  if(!(note||'').includes('44/12')||!(note||'').includes('t-CO₂/人'))failures.push(label+' CO2 conversion note missing: '+note);
  if(!(await page.locator('#consumption-history-chart canvas').count()))failures.push(label+' energy history chart canvas missing');
}

async function checkProcurementOverview(page,label,failures) {
  await page.waitForFunction(()=>/^\d+(?:\.\d+)?%$/.test((document.querySelector('#yoy-amount')?.textContent||'').trim()),{timeout:15000}).catch(()=>{});
  const procurementMeta=await page.evaluate(async()=>{const r=await fetch('/data/dashboard-meta.json');return r.ok?await r.json():{};}).catch(()=>({}));
  for(const city of ['横浜市','札幌市','神戸市','福岡市']){
    if(!(procurementMeta.a||[]).includes(city))failures.push(label+' municipal procurement agency missing: '+city);
  }
  const sourceText=(await page.locator('.quality-item',{hasText:'データソース内訳'}).textContent().catch(()=>''))||'';
  for(const city of ['横浜','札幌','神戸','福岡'])if(!sourceText.includes(city))failures.push(label+' source breakdown missing '+city);
  const yoyLabel=(await page.locator('#yoy-amount').locator('xpath=..').locator('.yoy-label').textContent().catch(()=>''))?.trim();
  const yoyValue=(await page.locator('#yoy-amount').textContent().catch(()=>''))?.trim();
  const yoyMeta=(await page.locator('#yoy-amount-meta').textContent().catch(()=>''))?.trim();
  if(yoyLabel!=='落札額が分かる案件')failures.push(label+' unclear award coverage label');
  if(!/^\d+(?:\.\d+)?%$/.test(yoyValue||''))failures.push(label+' award coverage is not a percentage: '+yoyValue);
  if(/比較注意|単純比較不可/.test((yoyValue||'')+' '+(yoyMeta||'')))failures.push(label+' confusing award comparison wording remains');
  if(!(yoyMeta||'').includes('件で金額確認済み'))failures.push(label+' award coverage count explanation missing');

  const groupTitle=(await page.locator('.card-head h3',{hasText:'大分類別構成'}).count())>0;
  if(!groupTitle)failures.push(label+' large-category chart title missing');
  const chart=page.locator('#chart-category');
  await chart.scrollIntoViewIfNeeded().catch(()=>{});
  const box=await chart.boundingBox();
  if(box){
    const m=Math.min(box.width,box.height);
    await chart.click({position:{x:box.width/2+m*.27,y:box.height*.39}}).catch(()=>{});
    await page.waitForTimeout(250);
    const drillVisible=await page.locator('#drill-card').isVisible().catch(()=>false);
    const drillTitle=(await page.locator('#drill-title').textContent().catch(()=>''))?.trim();
    const allowed=['IT・情報','建設・施設','物品・製造','委託・専門サービス','生活・公共サービス','インフラ・環境','手続・その他'];
    if(!drillVisible||!allowed.includes(drillTitle||''))failures.push(label+' large-category click/filter failed: '+drillTitle);
    if(drillVisible)await page.locator('#drill-clear').click().catch(()=>{});
  } else failures.push(label+' large-category chart missing');
}

(async()=>{
  fs.rmSync(shotRoot,{recursive:true,force:true});
  fs.mkdirSync(shotRoot,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const failures=[], warnings=[];
  console.log('E2E routes',activeRoutes.length,activeRoutes.join(' '));

  for (const vp of viewports) {
    const ctx=await browser.newContext({viewport:{width:vp.width,height:vp.height}});
    fs.mkdirSync(path.join(shotRoot,vp.name),{recursive:true});
    for (const route of activeRoutes) {
      const page=await ctx.newPage();
      const jsErrors=[],badFirstParty=[],badExternal=[];
      page.on('pageerror',e=>jsErrors.push(e.message));
      page.on('console',m=>{if(m.type()==='error'&&!/^Failed to load resource:/.test(m.text()))jsErrors.push(m.text())});
      page.on('response',r=>{
        if(r.status()<400)return;
        const u=new URL(r.url()),own=u.origin===new URL(base).origin;
        (own?badFirstParty:badExternal).push(r.status()+' '+r.url());
      });
      try {
        const res=await page.goto(base+encodeURI(route),{waitUntil:'networkidle',timeout:60000});
        if(!res||res.status()>=400)failures.push(`${vp.name} ${route} navigation ${res?.status()}`);
        const initialLabel=`${vp.name} ${route}`;
        if(route==='/procurement/')await checkProcurementOverview(page,initialLabel,failures);
        if(route==='/realestate/')await checkRealestateMapPalette(page,initialLabel,failures);
        if(route==='/regional/')await checkRegionalMunicipal(page,initialLabel,failures);
        if(route==='/economy-prices/')await checkEconomyPriceHistory(page,initialLabel,failures);
        if(route==='/energy/')await checkEnergyCo2History(page,initialLabel,failures);

        const filterToggle=page.locator('#filter-toggle:visible, #filters-toggle:visible');
        if(await filterToggle.count() && await filterToggle.first().getAttribute('aria-expanded')!=='true') await filterToggle.first().click();

        const tabs=page.locator('button.tab:visible');
        for(let i=0;i<await tabs.count();i++){
          await tabs.nth(i).click(); await page.waitForTimeout(120);
          if(await tabs.nth(i).getAttribute('aria-selected')!=='true')failures.push(`${vp.name} ${route} tab ${i} did not activate`);
          await exerciseVisibleSelects(page);
        }
        if(!(await tabs.count())) await exerciseVisibleSelects(page);

        const lazy=page.locator('button:visible').filter({hasText:/読み込|履歴|長期データ|全47都道府県/});
        for(let i=0;i<Math.min(await lazy.count(),3);i++){await lazy.nth(i).click().catch(()=>{});await page.waitForTimeout(180)}
        await page.waitForTimeout(350);

        const state=await page.evaluate(()=>{
          const visible=el=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
          const brand=document.querySelector('.brand');
          const brandImg=brand?.querySelector('img[src="/favicon.svg"]');
          const images=[...document.querySelectorAll('img')].filter(visible);
          const text=[...document.body.querySelectorAll('*')].filter(visible)
            .filter(el=>!['SCRIPT','STYLE'].includes(el.tagName))
            .map(el=>el.childElementCount===0?(el.textContent||'').trim():'').filter(Boolean).join(' ');
          const stuck=[...document.querySelectorAll('.loading,[id*="status"],[id*="note"]')]
            .filter(visible).map(el=>(el.textContent||'').trim()).filter(t=>/読み込み中|読込中/.test(t));
          const tables=[...document.querySelectorAll('table')].filter(visible);
          const emptyTables=tables.filter(t=>t.querySelectorAll('tbody tr').length===0).length;
          const statValues=[...document.querySelectorAll('.stats .value,.kpi-value')].filter(visible).map(e=>(e.textContent||'').trim());
          return {
            scrollWidth:document.documentElement.scrollWidth, clientWidth:document.documentElement.clientWidth,
            title:document.title.trim(), h1:(document.querySelector('h1')?.textContent||'').trim(),
            favicon:!!document.querySelector('link[rel="icon"][href="/favicon.svg"]'),
            canonical:!!document.querySelector('link[rel="canonical"][href]'),
            headerLogo:!!document.querySelector('header img[src="/favicon.svg"]'),
            brandSeen:!!brand, brandIcon:!!brandImg, brandIconLoaded:!brandImg||(brandImg.complete&&brandImg.naturalWidth>0),
            brokenImages:images.filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.getAttribute('src')).slice(0,5),
            badVisibleText:/(^|\W)(undefined|NaN)(\W|$)/.test(text),
            stuck, tables:tables.length, emptyTables, statValues,
            canvases:document.querySelectorAll('canvas').length
          };
        });

        const label=`${vp.name} ${route}`;
        if(!state.title)failures.push(label+' missing title');
        if(!state.h1)failures.push(label+' missing h1');
        if(!state.favicon)failures.push(label+' missing favicon');
        if(!state.canonical && route!=='/analytics/')failures.push(label+' missing canonical');
        if(!state.headerLogo)failures.push(label+' header logo icon missing');
        if(state.brandSeen&&!state.brandIcon)failures.push(label+' brand icon missing');
        if(!state.brandIconLoaded)failures.push(label+' brand icon failed to load');
        if(state.brokenImages.length)failures.push(label+' broken images '+state.brokenImages.join(','));
        if(state.badVisibleText)failures.push(label+' visible undefined/NaN');
        if(state.emptyTables)failures.push(label+` has ${state.emptyTables} empty visible table(s)`);
        if(state.statValues.length && state.statValues.every(v=>!v||v==='—'))failures.push(label+' all KPI/stat values empty');
        if(state.scrollWidth>state.clientWidth+2)failures.push(label+` overflow ${state.scrollWidth}>${state.clientWidth}`);
        if(state.stuck.length)failures.push(label+' stuck loading: '+state.stuck.slice(0,2).join(' | '));
        if(jsErrors.length)failures.push(label+' JS: '+unique(jsErrors).slice(0,2).join(' | '));
        if(badFirstParty.length)failures.push(label+' HTTP: '+unique(badFirstParty).slice(0,2).join(' | '));
        if(badExternal.length)warnings.push(label+' external HTTP: '+unique(badExternal).slice(0,3).join(' | '));

        await page.screenshot({path:path.join(shotRoot,vp.name,safeRoute(route)+'.jpg'),fullPage:true,type:'jpeg',quality:62});
        console.log('CHECK',label,'status',res?.status(),'brand',state.brandSeen?Number(state.brandIcon):'-','tables',state.tables,'canvas',state.canvases,'overflow',state.scrollWidth-state.clientWidth,'stuck',state.stuck.length,'js',jsErrors.length,'ownHTTP',badFirstParty.length,'externalHTTP',badExternal.length);
      } catch(e) {
        failures.push(`${vp.name} ${route} FATAL: ${e.message}`);
      }
      await page.close();
    }
    await ctx.close();
  }
  await browser.close();
  console.log('\nWARNINGS',warnings.length); warnings.forEach(x=>console.log('WARN',x));
  console.log('FAILURES',failures.length); failures.forEach(x=>console.log('FAIL',x));
  process.exit(failures.length?1:0);
})();
