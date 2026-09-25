const { chromium } = require('playwright');

const base = process.env.E2E_BASE_URL || 'https://datlume.com';
const routes = ['/procurement/','/realestate/','/regional/','/employment-economy/','/business-industry/','/economy-prices/','/energy/'];
const viewports = [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}];

const sleep = ms => new Promise(r => setTimeout(r, ms));
const unique = xs => [...new Set(xs)];
const numberFrom = text => { const m = String(text ?? '').replace(/,/g,'').match(/-?[0-9]+(?:\.[0-9]+)?/); return m ? Number(m[0]) : NaN; };
const near = (a,b,t=0.06) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a-b) <= t;

async function validateDomainNumbers(page, route, label, failures) {
  const fail = (name, actual, expected) => failures.push(`${label} ${route} data ${name}: actual=${actual} expected=${expected}`);
  if (route === '/procurement/') {
    const meta = await fetch(new URL('/data/dashboard-meta.json', base)).then(r=>r.json());
    const year = String(meta.latestYear ?? Math.max(...meta.years.map(Number)));
    const rows = await fetch(new URL(`/data/dashboard-${year}.json`, base)).then(r=>r.json());
    const actual = numberFrom(await page.locator('#kpi-count').textContent());
    if (actual !== rows.length) fail('kpi-count', actual, rows.length);
  } else if (route === '/realestate/') {
    const data = await fetch(new URL('/data/land-prices-2026.json', base)).then(r=>r.json());
    const actual = numberFrom(await page.locator('#kpi-count').textContent());
    if (actual !== data.records.length) fail('land-count', actual, data.records.length);
  } else if (route === '/regional/') {
    const data = await fetch(new URL('/data/regional-trends-2026.json', base)).then(r=>r.json());
    const pref = await page.locator('#pref').inputValue(), metric = await page.locator('#metric').inputValue();
    const rows = data.records.filter(r=>r.prefecture===pref && Number.isFinite(r[metric])).sort((a,b)=>a.year-b.year);
    const expected = rows.at(-1)?.[metric], actual = numberFrom(await page.locator('#a-value').textContent());
    if (!near(actual, expected, 0.06)) fail(`latest-${metric}`, actual, expected);
  } else if (route === '/employment-economy/') {
    const data = await fetch(new URL('/data/employment-economy-2026.json', base)).then(r=>r.json());
    const pref = await page.locator('#pref').inputValue(), row = data.records.find(r=>r.prefecture===pref);
    const expected = row?.estimatedAnnualCashThousandYen * 0.1, actual = numberFrom(await page.locator('#overview-pay').textContent());
    if (!near(actual, expected, 0.06)) fail('estimated-annual-pay', actual, expected);
  } else if (route === '/business-industry/') {
    const data = await fetch(new URL('/data/business-industry-2026.json', base)).then(r=>r.json());
    const vals = await page.locator('.kpi-value').evaluateAll(es=>es.map(e=>e.textContent));
    const est = numberFrom(vals[0]), emp = numberFrom(vals[1]);
    if (est !== data.totals.establishments) fail('establishments-total', est, data.totals.establishments);
    if (emp !== data.totals.employees) fail('employees-total', emp, data.totals.employees);
    const tableRows = await page.locator('#all-pref-table tbody tr').count();
    if (tableRows !== data.records.length) fail('prefecture-row-count', tableRows, data.records.length);
  } else if (route === '/economy-prices/') {
    const data = await fetch(new URL('/data/economy-prices.json', base)).then(r=>r.json());
    const pref = await page.locator('#pref').inputValue(), row = data.records.find(r=>r.prefecture===pref);
    const actual = numberFrom(await page.locator('#kpi-overall').textContent());
    if (!near(actual, row?.overall, 0.01)) fail('overall-index', actual, row?.overall);
  } else if (route === '/energy/') {
    const data = await fetch(new URL('/data/energy.json', base)).then(r=>r.json());
    const pref = await page.locator('#pref').inputValue(), row = data.records.find(r=>r.prefecture===pref);
    const energy = numberFrom(await page.locator('#kpi-energy').textContent()), price = numberFrom(await page.locator('#kpi-price').textContent());
    if (energy !== row?.monthlyEnergyYen) fail('monthly-energy', energy, row?.monthlyEnergyYen);
    if (!near(price, row?.utilityPriceIndex, 0.01)) fail('utility-price-index', price, row?.utilityPriceIndex);
  }
}

async function exerciseVisibleSelects(page) {
  const selects = page.locator('select:visible');
  for (let i = 0; i < await selects.count(); i++) {
    const select = selects.nth(i);
    const n = await select.locator('option').count();
    if (n > 1) {
      const current = await select.inputValue();
      const options = await select.locator('option').evaluateAll(os => os.map(o => o.value));
      const next = options.find(v => v && v !== current) ?? options.find(v => v !== current);
      if (next !== undefined) {
        await select.selectOption(next).catch(() => {});
        await page.waitForTimeout(100);
      }
    }
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const failures = [], warnings = [];

  for (const vp of viewports) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    for (const route of routes) {
      const page = await ctx.newPage();
      const jsErrors = [], badFirstParty = [], badExternal = [];

      page.on('pageerror', e => jsErrors.push(e.message));
      page.on('console', m => {
        if (m.type() === 'error' && !/^Failed to load resource:/.test(m.text())) jsErrors.push(m.text());
      });
      page.on('response', r => {
        if (r.status() < 400) return;
        const u = new URL(r.url());
        const own = u.origin === new URL(base).origin;
        (own ? badFirstParty : badExternal).push(r.status() + ' ' + r.url());
      });

      try {
        const res = await page.goto(base + route, { waitUntil: 'networkidle', timeout: 60000 });
        if (!res || res.status() >= 400) failures.push(`${vp.name} ${route} navigation ${res?.status()}`);

        await validateDomainNumbers(page, route, vp.name, failures);

        const filterToggle = page.locator('#filter-toggle:visible');
        if (await filterToggle.count()) {
          const expanded = await filterToggle.getAttribute('aria-expanded');
          if (expanded !== 'true') await filterToggle.click();
        }

        const tabs = page.locator('button.tab:visible');
        if (await tabs.count()) {
          for (let i = 0; i < await tabs.count(); i++) {
            await tabs.nth(i).click();
            await page.waitForTimeout(120);
            if (await tabs.nth(i).getAttribute('aria-selected') !== 'true') {
              failures.push(`${vp.name} ${route} tab ${i} did not activate`);
            }
            await exerciseVisibleSelects(page);
          }
        } else {
          await exerciseVisibleSelects(page);
        }

        const lazyButtons = page.locator('button:visible').filter({ hasText: /読み込|履歴|長期データ/ });
        for (let i = 0; i < Math.min(await lazyButtons.count(), 2); i++) {
          await lazyButtons.nth(i).click().catch(() => {});
          await page.waitForTimeout(250);
        }

        await page.waitForTimeout(300);
        const state = await page.evaluate(() => {
          const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
          const stuck = [...document.querySelectorAll('.loading,[id*="status"],[id*="note"]')]
            .filter(visible).map(el => (el.textContent || '').trim())
            .filter(t => /読み込み中|読込中/.test(t));
          return {
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            stuck,
            canvases: document.querySelectorAll('canvas').length
          };
        });

        if (state.scrollWidth > state.clientWidth + 2) failures.push(`${vp.name} ${route} overflow ${state.scrollWidth}>${state.clientWidth}`);
        if (state.stuck.length) failures.push(`${vp.name} ${route} stuck loading: ${state.stuck.slice(0,2).join(' | ')}`);
        if (jsErrors.length) failures.push(`${vp.name} ${route} JS: ${unique(jsErrors).slice(0,2).join(' | ')}`);
        if (badFirstParty.length) failures.push(`${vp.name} ${route} HTTP: ${unique(badFirstParty).slice(0,2).join(' | ')}`);
        if (badExternal.length) warnings.push(`${vp.name} ${route} external HTTP: ${unique(badExternal).slice(0,3).join(' | ')}`);

        console.log('CHECK', vp.name, route, 'status', res?.status(), 'tabs', await tabs.count(), 'canvas', state.canvases, 'overflow', state.scrollWidth-state.clientWidth, 'stuck', state.stuck.length, 'js', jsErrors.length, 'firstPartyHTTP', badFirstParty.length, 'externalHTTP', badExternal.length);
      } catch (e) {
        failures.push(`${vp.name} ${route} FATAL: ${e.message}`);
      }
      await page.close();
    }
    await ctx.close();
  }

  await browser.close();
  console.log('\nWARNINGS', warnings.length);
  warnings.forEach(x => console.log('WARN', x));
  console.log('FAILURES', failures.length);
  failures.forEach(x => console.log('FAIL', x));
  process.exit(failures.length ? 1 : 0);
})();