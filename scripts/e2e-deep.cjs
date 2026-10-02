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
const staticRoutes=['/','/about-data/','/analytics/','/topics/','/procurement/','/realestate/','/regional/','/employment-economy/','/business-industry/','/listed-companies/','/unlisted-companies/','/listed-companies/7203/','/listed-companies/compare/','/economy-prices/','/energy/'];
const listedIndexFile=path.join(process.cwd(),'public','data','listed-companies','index.json');
const listedIndex=fs.existsSync(listedIndexFile)?JSON.parse(fs.readFileSync(listedIndexFile,'utf8')).records||[]:[];
const listedNoFinancial=listedIndex.find(x=>x?.securityCode&&!x?.hasFinancials);
const listedNoFinancialRoute=listedNoFinancial?`/listed-companies/${listedNoFinancial.securityCode}/`:null;
if(listedNoFinancialRoute)staticRoutes.push(listedNoFinancialRoute);
const unlistedIndexFile=path.join(process.cwd(),'public','data','company-registry','unlisted-index.json');
const unlistedIndex=fs.existsSync(unlistedIndexFile)?JSON.parse(fs.readFileSync(unlistedIndexFile,'utf8')).records||[]:[];
const unlistedSample=unlistedIndex.find(x=>/^\d{13}$/.test(String(x?.corporateNumber||'')));
const unlistedDetailRoute=unlistedSample?`/unlisted-companies/${unlistedSample.corporateNumber}/`:null;
if(unlistedDetailRoute)staticRoutes.push(unlistedDetailRoute);
const unlistedFinanceCsvSample=unlistedIndex.find(x=>/^\d{13}$/.test(String(x?.corporateNumber||''))&&x?.financeSourceType==='finance');
const unlistedStatementSample=unlistedIndex.find(x=>/^\d{13}$/.test(String(x?.corporateNumber||''))&&x?.financeSourceType==='statements');
const unlistedFinanceCsvRoute=unlistedFinanceCsvSample?`/unlisted-companies/${unlistedFinanceCsvSample.corporateNumber}/`:null;
const unlistedStatementRoute=unlistedStatementSample?`/unlisted-companies/${unlistedStatementSample.corporateNumber}/`:null;
const unlistedNegativeSample=unlistedIndex.find(x=>/^\d{13}$/.test(String(x?.corporateNumber||''))&&x?.hasFinance&&Number(x?.latestNetIncome)<0);
const unlistedNegativeRoute=unlistedNegativeSample?`/unlisted-companies/${unlistedNegativeSample.corporateNumber}/`:null;
for(const route of [unlistedFinanceCsvRoute,unlistedStatementRoute,unlistedNegativeRoute])if(route&&route!==unlistedDetailRoute)staticRoutes.push(route);
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
  ['listed-industry', /^\/listed-companies\/industries\/輸送用機器\/$/],
  ['economy-pref', /^\/economy-prices\/prefectures\/北海道\/$/],
  ['economy-indicator', /^\/economy-prices\/indicators\/[^/]+\/$/],
  ['employment-pref', /^\/employment-economy\/prefectures\/北海道\/$/],
  ['employment-indicator', /^\/employment-economy\/indicators\/[^/]+\/$/],
  ['energy-pref', /^\/energy\/prefectures\/北海道\/$/],
  ['energy-indicator', /^\/energy\/indicators\/[^/]+\/$/],
  ['regional-pref', /^\/regional\/prefectures\/北海道\/$/],
  ['regional-indicator', /^\/regional\/indicators\/[^/]+\/$/],
];
const onlyRoutes=(process.env.E2E_ONLY||'').split(',').map(x=>x.trim()).filter(Boolean);
const localWithoutFunctions=/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?\/?$/i.test(base)&&process.env.E2E_INCLUDE_FUNCTIONS!=='1';
let activeRoutes;
if (onlyRoutes.length) {
  activeRoutes=[...new Set(onlyRoutes)];
} else {
  const routes=[...staticRoutes].filter(r=>!(localWithoutFunctions&&(
    /^\/listed-companies\/[0-9A-Z]{4}\/$/.test(r)||/^\/unlisted-companies\/\d{13}\/$/.test(r)
  )));
  for (const [name,re] of families) {
    if(localWithoutFunctions&&name==='proc-company')continue;
    let hit=builtRoutes.find(r=>re.test(r));
    if (!hit && name==='proc-company') {
      const companyFile=path.join(process.cwd(),'src','data','companies.json');
      const companies=fs.existsSync(companyFile)?JSON.parse(fs.readFileSync(companyFile,'utf8')):[];
      const company=[...companies].sort((a,b)=>Number(b.awardTotal||0)-Number(a.awardTotal||0))[0];
      if (company?.id) hit=`/procurement/companies/${company.id}/`;
    }
    if (!hit) throw new Error('No built route for family '+name);
    routes.push(hit);
  }
  activeRoutes=[...new Set(routes)];
}
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const unique = xs => [...new Set(xs)];
const safeRoute = r => (r==='/'?'home':r.replace(/^\//,'').replace(/\/$/,'').replace(/[^a-zA-Z0-9_-]+/g,'_')).slice(0,120);
const PREFECTURE_ORDER=['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県'];

async function checkUnlistedCompanies(page,label,failures) {
  await page.waitForFunction(()=>!/読み込み中/.test(document.querySelector('#result-count')?.textContent||''),{timeout:10000}).catch(()=>{});
  const prefFilter=page.locator('#pref-filter');
  if(await prefFilter.count()){
    const actual=(await prefFilter.locator('option').evaluateAll(os=>os.map(o=>o.value).filter(Boolean)));
    const present=new Set(unlistedIndex.map(x=>x?.prefecture).filter(Boolean));
    const expected=PREFECTURE_ORDER.filter(p=>present.has(p));
    if(JSON.stringify(actual)!==JSON.stringify(expected))failures.push(label+' prefecture order mismatch '+actual.slice(0,5).join(',')+' ... '+actual.slice(-3).join(','));
  }
  const financeFilter=page.locator('#finance-filter');
  if(await financeFilter.count()){
    for(const [value,predicate,name] of [
      ['yes',x=>x?.hasFinance,'all finance'],
      ['csv',x=>x?.financeSourceType==='finance','finance CSV'],
      ['statements',x=>x?.hasFinancialStatements,'statements'],
    ]){
      await financeFilter.selectOption(value); await page.waitForTimeout(120);
      const expected=unlistedIndex.filter(predicate).length;
      const text=(await page.locator('#result-count').textContent()||'').replace(/,/g,'');
      if(!text.includes(String(expected)))failures.push(label+' '+name+' filter count '+text+' expected '+expected);
      const cards=page.locator('.company-card:visible'); const n=await cards.count();
      if(expected&&!n)failures.push(label+' '+name+' filter returned no cards');
      for(let i=0;i<Math.min(n,24);i++)if(!(await cards.nth(i).locator('.finance-tag').count()))failures.push(label+' '+name+' card missing finance badge');
    }
    await financeFilter.selectOption(''); await page.waitForTimeout(80);
  }
}

async function checkUnlistedCompanyDetail(page,label,failures) {
  const allRows=page.locator('tbody tr');
  const rows=page.locator('tbody tr:visible');
  const more=page.locator('[data-show-more]');
  const total=await allRows.count();
  const expectedInitial=Math.min(20,total);
  const before=await rows.count();
  if(before!==expectedInitial)failures.push(label+' initial procurement rows '+before+' expected '+expectedInitial);
  if(await more.count()){
    await more.click(); await page.waitForTimeout(80);
    const expanded=await rows.count();
    if(expanded!==total)failures.push(label+' expanded procurement rows '+expanded+' expected '+total);
    await more.click(); await page.waitForTimeout(80);
    const collapsed=await rows.count();
    if(collapsed!==expectedInitial)failures.push(label+' collapsed procurement rows '+collapsed+' expected '+expectedInitial);
  }
  const route=new URL(page.url()).pathname;
  const m=route.match(/^\/unlisted-companies\/(\d{13})\/$/);
  const sample=m?unlistedIndex.find(x=>String(x?.corporateNumber||'')===m[1]):null;
  if(sample?.hasFinance){
    const expected=Number(sample.financePeriods||0);
    const history=await page.locator('.finance-period-card').count();
    if(history!==expected)failures.push(label+' finance period cards '+history+' expected '+expected);
    const initialVisible=await page.locator('.finance-period-card:visible').count();
    if(initialVisible!==1)failures.push(label+' initial visible finance periods '+initialVisible+' expected 1');
    const disclosure=page.locator('.finance-history-more');
    if(expected>1){
      if(!(await disclosure.count()))failures.push(label+' finance history disclosure missing');
      else {
        const summaryEl=disclosure.locator('summary');
        const summary=(await summaryEl.textContent()||'').replace(/\s+/g,'');
        const expectedClosed=sample.financeSourceType==='statements'?`過去${expected-1}期の決算公告を見る`:`過去${expected-1}期の推移を見る`;
        if(!summary.includes(expectedClosed))failures.push(label+' finance history summary '+summary+' expected '+expectedClosed);
        const ctaStyle=await summaryEl.evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color,width:el.getBoundingClientRect().width,parent:el.parentElement?.getBoundingClientRect().width||0}));
        if(ctaStyle.background!=='rgb(9, 24, 39)')failures.push(label+' finance history CTA background '+ctaStyle.background+' expected rgb(9, 24, 39)');
        if(ctaStyle.color!=='rgb(255, 255, 255)')failures.push(label+' finance history CTA color '+ctaStyle.color+' expected white');
        if(Math.abs(ctaStyle.width-ctaStyle.parent)>2)failures.push(label+' finance history CTA width '+ctaStyle.width+' parent '+ctaStyle.parent);
        await summaryEl.click(); await page.waitForTimeout(60);
        const openSummary=(await summaryEl.textContent()||'').replace(/\s+/g,'');
        if(!openSummary.includes(`過去${expected-1}期を閉じる`))failures.push(label+' finance history open summary '+openSummary+' expected close label');
        const expandedVisible=await page.locator('.finance-period-card:visible').count();
        if(expandedVisible!==expected)failures.push(label+' expanded visible finance periods '+expandedVisible+' expected '+expected);
        await disclosure.locator('summary').click(); await page.waitForTimeout(60);
        const collapsedVisible=await page.locator('.finance-period-card:visible').count();
        if(collapsedVisible!==1)failures.push(label+' collapsed visible finance periods '+collapsedVisible+' expected 1');
      }
    } else if(await disclosure.count()) failures.push(label+' single-period finance unexpectedly has disclosure');
    if(!(await page.locator('.finance-source-line').count()))failures.push(label+' finance source line missing');
    if(await page.locator('.finance-empty').count())failures.push(label+' finance page shows empty state');
    const summaryCards=await page.locator('.finance-panel .finance-card-grid .finance-metric').count();
    if(summaryCards<4)failures.push(label+' finance summary cards '+summaryCards+' expected at least 4');
    if(sample.financeSourceType==='statements'){
      const source=(await page.locator('.finance-source-line').textContent()||'');
      if(!/決算情報|官報/.test(source))failures.push(label+' statement source label missing');
      const title=(await page.locator('.finance-history-panel h2').textContent()||'');
      if(!title.includes('決算公告の推移'))failures.push(label+' statement history title missing');
    }
    if(Number(sample.latestNetIncome)<0){
      const negatives=page.locator('.finance-metric b.negative');
      if(!(await negatives.count()))failures.push(label+' negative finance value lacks negative class');
      else {
        const color=await negatives.first().evaluate(el=>getComputedStyle(el).color);
        if(color!=='rgb(201, 42, 42)')failures.push(label+' negative finance color '+color+' expected rgb(201, 42, 42)');
      }
    }
  }
}

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
  const housingMeta=await page.evaluate(async()=>{const r=await fetch('/data/housing-land-2023.json');if(!r.ok)return{};const d=await r.json();return{count:d.records?.length,national:d.national,surveyDate:d.surveyDate}}).catch(()=>({}));
  if(housingMeta.count!==1059||housingMeta.surveyDate!=='2023-10-01')failures.push(label+' housing dataset coverage invalid: '+JSON.stringify(housingMeta));
  for(const [kind,colors,legendText] of [['vacancy',['#ccfbf1','#0f766e'],'空き家率（2023）'],['owner',['#e0f2fe','#075985'],'持ち家率（2023）']]){
    await page.evaluate(k=>{const el=document.querySelector('#stat-layer');if(el){el.value=k;el.dispatchEvent(new Event('change',{bubbles:true}));}},kind).catch(()=>{});
    await page.waitForFunction(()=>window.__DATLUME_MAP__?.getLayer?.('housing-stat-points'),{timeout:5000}).catch(()=>{});
    await page.waitForTimeout(120);
    const state=await page.evaluate(()=>({paint:window.__DATLUME_MAP__?.getPaintProperty?.('housing-stat-points','circle-color'),visible:window.__DATLUME_MAP__?.getLayoutProperty?.('housing-stat-points','visibility'),legend:document.querySelector('#legend')?.textContent||''})).catch(()=>({}));
    const enc=JSON.stringify(state.paint||[]);
    for(const color of colors)if(!enc.includes(color))failures.push(label+' '+kind+' housing palette missing '+color);
    if(state.visible==='none')failures.push(label+' '+kind+' housing layer did not become visible');
    if(!String(state.legend||'').includes(legendText))failures.push(label+' '+kind+' housing legend missing');
  }
  const tradeMeta=await page.evaluate(async()=>{const r=await fetch('/data/realestate-transactions.json');if(!r.ok)return{};const d=await r.json();return{municipalities:d.municipalities?.length,prefectures:d.prefectures?.length,records:d.publishedResidentialRecords,latest:d.latestPeriod,periodLabel:d.periodLabel,acquisition:d.acquisition,unmapped:d.unmappedRecords,minSample:d.minSampleForMap,segments:d.national?.segments}}).catch(()=>({}));
  if((tradeMeta.municipalities||0)<1600||tradeMeta.prefectures!==47||(tradeMeta.records||0)<200000||!/^20\d{2}Q[1-4]$/.test(tradeMeta.latest||'')||tradeMeta.acquisition!=='official-api-XIT001'||tradeMeta.unmapped!==0||tradeMeta.minSample!==5)failures.push(label+' transaction dataset coverage invalid: '+JSON.stringify(tradeMeta));
  for(const key of ['land','house','condo'])if(!(tradeMeta.segments?.[key]?.count>10000))failures.push(label+' transaction segment missing: '+key);
  for(const [kind,colors,legendText,countField] of [['tradeLand',['#eef2ff','#4338ca'],'土地の実取引㎡単価','landCount'],['tradeHouse',['#fff1f2','#be123c'],'土地+建物の実取引価格','houseCount'],['tradeCondo',['#ecfeff','#0e7490'],'中古マンション等の実取引㎡単価','condoCount']]){
    await page.evaluate(k=>{const el=document.querySelector('#stat-layer');if(el){el.value=k;el.dispatchEvent(new Event('change',{bubbles:true}));}},kind).catch(()=>{});
    await page.waitForFunction(()=>window.__DATLUME_MAP__?.getLayer?.('transaction-stat-points'),{timeout:5000}).catch(()=>{});
    await page.waitForTimeout(120);
    const state=await page.evaluate(()=>({paint:window.__DATLUME_MAP__?.getPaintProperty?.('transaction-stat-points','circle-color'),filter:window.__DATLUME_MAP__?.getFilter?.('transaction-stat-points'),visible:window.__DATLUME_MAP__?.getLayoutProperty?.('transaction-stat-points','visibility'),legend:document.querySelector('#legend')?.textContent||'',status:document.querySelector('#map-status')?.textContent||''})).catch(()=>({}));
    const enc=JSON.stringify(state.paint||[]),filter=JSON.stringify(state.filter||[]);
    for(const color of colors)if(!enc.includes(color))failures.push(label+' '+kind+' transaction palette missing '+color);
    if(state.visible==='none')failures.push(label+' '+kind+' transaction layer did not become visible');
    if(!filter.includes(countField)||!filter.includes('5'))failures.push(label+' '+kind+' transaction sample filter invalid: '+filter);
    if(!String(state.legend||'').includes(legendText)||!String(state.legend||'').includes('5件以上'))failures.push(label+' '+kind+' transaction legend missing');
    if(!String(state.status||'').includes(tradeMeta.periodLabel||''))failures.push(label+' '+kind+' transaction period status missing: '+state.status);
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
  await page.selectOption('#municipal-pref','').catch(()=>{});await page.selectOption('#municipal-metric','vacantHouseRate').catch(()=>{});await page.waitForTimeout(150);
  const vacancy=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(vacancy||'').includes('1,059市区町村')||!(vacancy||'').includes('空き家率')||!(vacancy||'').includes('2023年値'))failures.push(label+' municipal vacancy filter failed: '+vacancy);
  await page.selectOption('#municipal-metric','ownerOccupiedRate').catch(()=>{});await page.waitForTimeout(150);
  const owner=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(owner||'').includes('1,059市区町村')||!(owner||'').includes('持ち家率')||!(owner||'').includes('2023年値'))failures.push(label+' municipal owner-occupied filter failed: '+owner);
  await page.selectOption('#municipal-metric','physicians').catch(()=>{});await page.waitForTimeout(150);
  const physicians=(await page.locator('#municipal-status').textContent().catch(()=>''))?.trim();
  if(!(physicians||'').includes('1,741市区町村')||!(physicians||'').includes('医師数')||!(physicians||'').includes('2022年値'))failures.push(label+' municipal physician filter failed: '+physicians);
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

async function checkAboutDataAwardCoverage(page,label,failures) {
  const card=page.locator('.stats .card',{hasText:'総額を確認できる結果案件'}).first();
  if(!(await card.count())){failures.push(label+' award coverage card missing');return}
  const value=(await card.locator('.value').textContent().catch(()=>''))?.trim()||'';
  const meta=(await card.locator('.label').nth(1).textContent().catch(()=>''))?.trim()||'';
  const award=Number(value.replace(/[^0-9]/g,''));
  const m=meta.match(/判定対象\s*([0-9,]+)件の約\s*([0-9.]+)%/);
  if(!m){failures.push(label+' award coverage denominator label invalid: '+meta);return}
  const eligible=Number(m[1].replace(/,/g,'')); const shown=Number(m[2]);
  const expected=eligible?Number((award/eligible*100).toFixed(1)):0;
  if(shown!==expected)failures.push(label+` award coverage mismatch: ${shown}% != ${expected}% (${award}/${eligible})`);
  if(meta.includes('全収録レコード'))failures.push(label+' award coverage still uses all-record denominator');
}

async function checkProcurementOverview(page,label,failures) {
  await page.waitForFunction(()=>/^\d+(?:\.\d+)?%$/.test((document.querySelector('#yoy-amount')?.textContent||'').trim()),{timeout:15000}).catch(()=>{});
  const procurementMeta=await page.evaluate(async()=>{const r=await fetch('/data/dashboard-meta.json');return r.ok?await r.json():{};}).catch(()=>({}));
  for(const city of ['横浜市','札幌市','神戸市','福岡市','千葉市','京都市']){
    if(!(procurementMeta.a||[]).includes(city))failures.push(label+' municipal procurement agency missing: '+city);
  }
  const sourceText=(await page.locator('.quality-item',{hasText:'データソース内訳'}).textContent().catch(()=>''))||'';
  for(const city of ['横浜','札幌','神戸','福岡','千葉','京都'])if(!sourceText.includes(city))failures.push(label+' source breakdown missing '+city);
  const yoyLabel=(await page.locator('#yoy-amount').locator('xpath=..').locator('.yoy-label').textContent().catch(()=>''))?.trim();
  const yoyValue=(await page.locator('#yoy-amount').textContent().catch(()=>''))?.trim();
  const yoyMeta=(await page.locator('#yoy-amount-meta').textContent().catch(()=>''))?.trim();
  const kpiAwardMeta=(await page.locator('#kpi-awards').textContent().catch(()=>''))?.trim();
  const expectedCoverage=await page.evaluate(async()=>{
    const meta=await fetch('/data/dashboard-meta.json').then(r=>r.json());
    const year=meta.latestYear;const info=Array.isArray(meta.shardInfo)?meta.shardInfo:[];
    const names=info.filter(s=>(s.years||[]).includes(year)).map(s=>s.name);
    const yearRows=(await Promise.all(names.map(n=>fetch('/data/'+n).then(r=>r.json())))).flat();
    const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Tokyo'}).replaceAll('-','');
    const dates=yearRows.map(r=>String(r[2]||'')).filter(d=>d&&d<=today).sort();
    const cutoff=(dates.at(-1)||String(year)+'1231').slice(4);
    const rows=yearRows.filter(r=>String(r[2]||'').slice(4)<=cutoff);
    const awards=rows.filter(r=>Number(r[10]||0)>0).length;
    const eligible=rows.filter(r=>Number(r[12]||0)!==0).length;
    const kpiAwards=yearRows.filter(r=>Number(r[10]||0)>0).length;
    const kpiEligible=yearRows.filter(r=>Number(r[12]||0)!==0).length;
    return {awards,eligible,value:eligible?(awards/eligible*100).toFixed(1)+'%':'0.0%',kpiEligible,kpiValue:kpiEligible?(kpiAwards/kpiEligible*100).toFixed(1)+'%':'0.0%'};
  }).catch(()=>({awards:0,eligible:0,value:''}));
  if(yoyLabel!=='総額を確認できる結果案件')failures.push(label+' unclear award coverage label');
  if(yoyValue!==expectedCoverage.value)failures.push(label+' award coverage denominator mismatch: '+yoyValue+' != '+expectedCoverage.value);
  if(/比較注意|単純比較不可/.test((yoyValue||'')+' '+(yoyMeta||'')))failures.push(label+' confusing award comparison wording remains');
  const eligibleText=new Intl.NumberFormat('ja-JP').format(expectedCoverage.eligible);
  if(!(yoyMeta||'').includes('判定対象 '+eligibleText+'件'))failures.push(label+' award coverage eligible count missing: '+yoyMeta);
  if(!(kpiAwardMeta||'').includes('判定対象 '+new Intl.NumberFormat('ja-JP').format(expectedCoverage.kpiEligible)+'件の'+expectedCoverage.kpiValue))failures.push(label+' KPI award coverage denominator mismatch: '+kpiAwardMeta);

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


async function checkListedCompare(page,label,failures) {
  await page.waitForFunction(()=>document.querySelector('#company-search'),{timeout:15000}).catch(()=>{});
  for (const code of ['7203','9432']) {
    await page.fill('#company-search',code).catch(()=>{});
    await page.waitForTimeout(120);
    const choice=page.locator('#matches button[data-code="'+code+'"]').first();
    if(await choice.count()) await choice.click();
    await page.click('#add-company').catch(()=>{});
    await page.waitForTimeout(220);
  }
  await page.waitForFunction(()=>document.querySelectorAll('.compare-table thead th').length>=3,{timeout:15000}).catch(()=>{});
  const heads=await page.locator('.compare-table thead th').allTextContents().catch(()=>[]);
  if(!heads.some(x=>x.includes('トヨタ'))||!heads.some(x=>x.includes('ＮＴＴ')))failures.push(label+' comparison companies missing: '+heads.join(' / '));
  await page.waitForFunction(()=>document.querySelector('#history-chart canvas'),{timeout:15000}).catch(()=>{});
  if((await page.locator('#history-chart canvas').count())<1)failures.push(label+' comparison history chart missing');
  const url=page.url();
  if(!url.includes('codes=7203%2C9432')&&!url.includes('codes=7203,9432'))failures.push(label+' comparison URL state missing: '+url);
}

async function checkListedCompanyDetail(page,label,failures) {
  const h1=(await page.locator('h1').textContent().catch(()=>''))?.trim();
  if(!h1?.includes('トヨタ'))failures.push(label+' Toyota detail h1 mismatch: '+h1);
  const title=await page.title();
  if(!title.includes('業績・年収・財務分析'))failures.push(label+' SEO title missing intent terms: '+title);
  const meta=await page.locator('meta[name="description"]').getAttribute('content').catch(()=>null);
  if(!meta||meta.length<80)failures.push(label+' meta description too short: '+String(meta?.length||0));
  const canonical=await page.locator('link[rel="canonical"]').getAttribute('href').catch(()=>null);
  if(canonical!=='https://datlume.com/listed-companies/7203/')failures.push(label+' canonical mismatch: '+canonical);
  const robots=await page.locator('meta[name="robots"]').getAttribute('content').catch(()=>null);
  if(robots?.includes('noindex'))failures.push(label+' indexable company unexpectedly noindex: '+robots);
  const ldTexts=await page.locator('script[type="application/ld+json"]').allTextContents().catch(()=>[]);
  let ldTypes=[];
  for(const text of ldTexts){try{const x=JSON.parse(text); const graph=x?.['@graph']||[x]; ldTypes.push(...graph.map(v=>v?.['@type']).filter(Boolean));}catch{}}
  if(!ldTypes.includes('Corporation')||!ldTypes.includes('BreadcrumbList')||!ldTypes.includes('WebPage'))failures.push(label+' structured data missing types: '+ldTypes.join(','));
  const brandAlt=await page.locator('.brand img').getAttribute('alt').catch(()=>null);
  if(!brandAlt)failures.push(label+' brand image alt missing');
  const summary=(await page.locator('main .section-card h2').first().textContent().catch(()=>''))||'';
  if(!summary.includes('最新業績')&&!summary.includes('企業概要'))failures.push(label+' SEO summary section missing');
  const values=await page.locator('.kpi-value').allTextContents().catch(()=>[]);
  if(values.length<4||values.every(v=>!v.trim()||v.trim()==='—'))failures.push(label+' company KPI values missing');
  await page.waitForFunction(()=>document.querySelector('#financial-timeline canvas'),{timeout:15000}).catch(()=>{});
  if((await page.locator('#financial-timeline canvas').count())<1)failures.push(label+' financial timeline missing');
  const source=(await page.locator('.source').last().textContent().catch(()=>''))||'';
  if(!source.includes('EDINET'))failures.push(label+' EDINET source note missing');
}

async function checkListedNoFinancial(page,label,failures) {
  const robots=await page.locator('meta[name="robots"]').getAttribute('content').catch(()=>null);
  if(!robots?.includes('noindex'))failures.push(label+' no-financial company missing noindex: '+robots);
  const notice=(await page.locator('.notice').textContent().catch(()=>''))||'';
  if(!notice.includes('財務データ'))failures.push(label+' no-financial notice missing');
  if(await page.locator('#financial-timeline canvas').count())failures.push(label+' no-financial timeline unexpectedly rendered');
}

async function checkListedCompanies(page,label,failures) {
  await page.waitForFunction(()=>/社$/.test((document.querySelector('#result-count')?.textContent||'').trim()),{timeout:15000}).catch(()=>{});
  const initial=(await page.locator('#result-count').textContent().catch(()=>''))?.trim();
  if(!/^[\d,]+社$/.test(initial||''))failures.push(label+' listed-company count invalid: '+initial);
  if((await page.locator('.company-card').count())<1)failures.push(label+' listed-company cards missing');
  await page.waitForFunction(()=>document.querySelector('#scatter canvas'),{timeout:15000}).catch(()=>{});
  if(!(await page.locator('#scatter canvas').count()))failures.push(label+' listed-company scatter missing');
  if(await page.locator('#scatter-empty').isVisible().catch(()=>false))failures.push(label+' scatter empty-state visible with chart');
  await page.fill('#company-q','7203').catch(()=>{});
  await page.waitForTimeout(150);
  const filtered=(await page.locator('#result-count').textContent().catch(()=>''))?.trim();
  const firstHref=await page.locator('.company-card').first().getAttribute('href').catch(()=>null);
  if(filtered!=='1社'||firstHref!=='/listed-companies/7203/')failures.push(label+' company search failed: '+filtered+' '+firstHref);
  await page.fill('#company-q','').catch(()=>{});
  await page.selectOption('#market-filter','プライム').catch(()=>{});
  await page.waitForTimeout(120);
  const prime=(await page.locator('#result-count').textContent().catch(()=>''))?.trim();
  if(!/^[\d,]+社$/.test(prime||'')||prime==='0社')failures.push(label+' market filter failed: '+prime);
}

async function checkTopics(page,label,failures) {
  const file=path.join(process.cwd(),'public','data','wikipedia-topics.json');
  const data=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{};
  const items=data?.youtube?.items||[];
  const section=page.locator('.youtube-section');
  if(!items.length){
    if(await section.count())failures.push(label+' YouTube section visible without matched videos');
    return;
  }
  if(await section.count()!==1)failures.push(label+' YouTube section missing');
  const cards=page.locator('.youtube-card');
  if(await cards.count()!==items.length)failures.push(label+' YouTube card count mismatch');
  const first=page.locator('[data-youtube-play]').first();
  if(await first.count()){
    await first.click();
    const frame=page.locator('.youtube-frame').first();
    const src=await frame.getAttribute('src').catch(()=>null);
    if(!src?.startsWith('https://www.youtube-nocookie.com/embed/'))failures.push(label+' YouTube privacy embed failed');
  }
}

(async()=>{
  fs.rmSync(shotRoot,{recursive:true,force:true});
  fs.mkdirSync(shotRoot,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const failures=[], warnings=[];
  if(localWithoutFunctions&&!onlyRoutes.length)console.log('E2E local mode: Cloudflare Pages Function routes are covered separately on production');
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
        if(route==='/about-data/')await checkAboutDataAwardCoverage(page,initialLabel,failures);
        if(route==='/topics/')await checkTopics(page,initialLabel,failures);
    if(route==='/procurement/')await checkProcurementOverview(page,initialLabel,failures);
        if(route==='/realestate/')await checkRealestateMapPalette(page,initialLabel,failures);
        if(route==='/regional/')await checkRegionalMunicipal(page,initialLabel,failures);
        if(route==='/economy-prices/')await checkEconomyPriceHistory(page,initialLabel,failures);
        if(route==='/energy/')await checkEnergyCo2History(page,initialLabel,failures);
        if(route==='/listed-companies/')await checkListedCompanies(page,initialLabel,failures);
        if(route==='/listed-companies/7203/')await checkListedCompanyDetail(page,initialLabel,failures);
        if(listedNoFinancialRoute&&route===listedNoFinancialRoute)await checkListedNoFinancial(page,initialLabel,failures);
        if(route==='/listed-companies/compare/')await checkListedCompare(page,initialLabel,failures);
        if(route==='/unlisted-companies/')await checkUnlistedCompanies(page,initialLabel,failures);
        if(/^\/unlisted-companies\/\d{13}\/$/.test(route))await checkUnlistedCompanyDetail(page,initialLabel,failures);

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
            scrollHeight:document.documentElement.scrollHeight,
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

        const fullPageShot=state.scrollHeight<=30000;
        await page.screenshot({path:path.join(shotRoot,vp.name,safeRoute(route)+'.jpg'),fullPage:fullPageShot,type:'jpeg',quality:62});
        console.log('CHECK',label,'status',res?.status(),'brand',state.brandSeen?Number(state.brandIcon):'-','tables',state.tables,'canvas',state.canvases,'overflow',state.scrollWidth-state.clientWidth,'stuck',state.stuck.length,'js',jsErrors.length,'ownHTTP',badFirstParty.length,'externalHTTP',badExternal.length,'shot',fullPageShot?'full':'viewport');
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
