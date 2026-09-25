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

(async()=>{
  fs.rmSync(shotRoot,{recursive:true,force:true});
  fs.mkdirSync(shotRoot,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const failures=[], warnings=[];
  console.log('E2E routes',uniqueRoutes.length,uniqueRoutes.join(' '));

  for (const vp of viewports) {
    const ctx=await browser.newContext({viewport:{width:vp.width,height:vp.height}});
    fs.mkdirSync(path.join(shotRoot,vp.name),{recursive:true});
    for (const route of uniqueRoutes) {
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
