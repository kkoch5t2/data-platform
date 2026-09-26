const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'SAMEORIGIN',
  'Permissions-Policy': 'geolocation=(), camera=(), microphone=()',
};

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeUrl(value) {
  try {
    const u = new URL(String(value || ''));
    return (u.protocol === 'https:' || u.protocol === 'http:') ? u.href : '#';
  } catch {
    return '#';
  }
}

function fmt(value) {
  return new Intl.NumberFormat('ja-JP').format(Number(value || 0));
}

function oku(value) {
  const n = Number(value || 0);
  return `${(n / 100000000).toFixed(n >= 1000000000 ? 1 : 2)}億円`;
}

async function loadCompany(context, id) {
  const bucket = id.slice(3, 5).toLowerCase();
  const assetUrl = new URL(`/data/company-details/${bucket}.json`, context.request.url);
  const res = await context.env.ASSETS.fetch(assetUrl);
  if (!res.ok) return null;
  const payload = await res.json();
  return payload?.c?.[id] || null;
}

function renderCompany(id, item) {
  const [name, awardCount, awardTotal, rows] = item;
  const agency = new Map();
  for (const r of rows) agency.set(r[1], (agency.get(r[1]) || 0) + Number(r[4] || 0));
  const topAgency = [...agency.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = Math.max(...topAgency.map(([, v]) => v), 1);
  const description = `${name}の公共調達における落札件数、確認済み受注額、主な案件をまとめたデータページです。`;
  const canonical = `https://datlume.com/procurement/companies/${id}/`;
  const bars = topAgency.map(([agencyName, value]) => `<div class="barrow"><div>${esc(agencyName)}</div><div class="track"><div class="bar" style="width:${Math.max(0, Math.min(100, value / max * 100)).toFixed(2)}%"></div></div><div class="amount">${esc(oku(value))}</div></div>`).join('');
  const tableRows = rows.map((r) => `<tr><td>${esc(r[0] || '—')}</td><td>${esc(r[1])}</td><td class="title"><a href="${esc(safeUrl(r[3]))}" target="_blank" rel="noreferrer">${esc(r[2])}</a></td><td>${esc(fmt(r[4]))}円</td></tr>`).join('');
  const average = rows.length ? oku(Number(awardTotal || 0) / rows.length) : '—';
  return `<!doctype html><html lang="ja"><head><link rel="icon" type="image/svg+xml" href="/favicon.svg"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="description" content="${esc(description)}"><link rel="canonical" href="${esc(canonical)}"><meta property="og:title" content="${esc(name)} 公共調達データ | DATLUME"><meta property="og:description" content="${esc(description)}"><meta property="og:type" content="website"><meta name="twitter:card" content="summary"><link rel="stylesheet" href="/procurement-company.css"><title>${esc(name)} 公共調達データ | DATLUME</title></head><body>
<header><div class="wrap"><div class="nav"><a class="brand" href="/" aria-label="DATLUME" style="display:inline-flex;align-items:center;gap:10px;text-decoration:none;color:#fff"><img src="/favicon.svg" alt="" width="24" height="24" style="display:block;width:24px;height:24px;filter:brightness(0) invert(1)"><span style="font-family:'Segoe UI Variable','Avenir Next','Helvetica Neue',system-ui,sans-serif;font-size:19px;font-weight:750;letter-spacing:.16em;line-height:1">DATLUME</span></a><a class="back" href="/procurement/companies/">企業一覧</a></div><div class="hero"><div class="eyebrow">Vendor</div><h1>${esc(name)}</h1><p>公開調達情報から集計した分野横断の落札実績。</p></div></div></header>
<main class="wrap"><div class="stats"><div class="card"><div class="label">受注総額</div><div class="value">${esc(oku(awardTotal))}</div></div><div class="card"><div class="label">落札件数</div><div class="value">${esc(fmt(awardCount))}</div></div><div class="card"><div class="label">平均受注額</div><div class="value">${esc(average)}</div></div></div>
<section class="card section"><h2>主な発注機関</h2>${bars || '<div class="note">金額を確認できる案件はありません。</div>'}</section>
<section class="card table-card section"><div class="table-head"><h2>落札案件</h2><div class="note">金額確認済み ${esc(fmt(rows.length))}件</div></div><div style="overflow-x:auto"><table><thead><tr><th>落札日</th><th>発注機関</th><th>案件</th><th>金額</th></tr></thead><tbody>${tableRows}</tbody></table></div></section></main>
<footer class="wrap">出典：JETRO / 調達ポータル（GEPS） / 各自治体の公式入札・契約情報 ・ <a href="/about-data/#procurement">収録範囲と集計上の注意</a> · <a href="https://github.com/kkoch5t2/data-platform" target="_blank" rel="noreferrer" style="display:inline-flex;align-items:center;gap:5px"><img src="/brand/github.svg" alt="" width="14" height="14" style="display:block;width:14px;height:14px">GitHub ↗</a> · <a href="https://utility-tools-jp.com/" target="_blank" rel="noreferrer" style="display:inline-flex;align-items:center;gap:5px"><img src="/brand/utility-tools.ico" alt="" width="14" height="14" style="display:block;width:14px;height:14px;border-radius:3px">無料WEB便利ツール集 ↗</a></footer></body></html>`;
}

async function handle(context, headOnly = false) {
  const id = String(context.params.id || '').toLowerCase();
  if (!/^co_[0-9a-f]{12}$/.test(id)) return new Response('Not Found', { status: 404, headers: SECURITY_HEADERS });
  const item = await loadCompany(context, id);
  if (!item) return new Response('Not Found', { status: 404, headers: SECURITY_HEADERS });
  const body = headOnly ? null : renderCompany(id, item);
  return new Response(body, {
    status: 200,
    headers: {
      ...SECURITY_HEADERS,
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'public, max-age=3600, stale-while-revalidate=86400',
    },
  });
}

export function onRequestGet(context) { return handle(context, false); }
export function onRequestHead(context) { return handle(context, true); }
