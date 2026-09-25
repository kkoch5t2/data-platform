const { chromium } = require('playwright');

const base = process.env.E2E_BASE_URL || 'https://datlume.com';
const routes = ['/procurement/','/realestate/','/regional/','/employment-economy/','/business-industry/','/economy-prices/','/energy/'];
const viewports = [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}];

const sleep = ms => new Promise(r => setTimeout(r, ms));
const unique = xs => [...new Set(xs)];

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

        const filterToggle = page.locator('#filters-toggle:visible');
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