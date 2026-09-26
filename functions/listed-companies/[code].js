const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'SAMEORIGIN',
  'Permissions-Policy': 'geolocation=(), camera=(), microphone=()',
};

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function detailBucket(code) {
  let value = 0;
  for (const ch of code) value = (value * 31 + ch.charCodeAt(0)) % 64;
  return value.toString(16).padStart(2, '0');
}

async function loadCompany(context, code) {
  const assetUrl = new URL(`/data/listed-companies/details/${detailBucket(code)}.json`, context.request.url);
  const res = await context.env.ASSETS.fetch(assetUrl);
  if (!res.ok) return null;
  const payload = await res.json();
  return payload?.c?.[code] || null;
}
function money(value) {
  if (value == null) return '—';
  const n=Number(value), a=Math.abs(n), sign=n<0?'-':'';
  if (a>=1e12) return `${sign}${(a/1e12).toLocaleString('ja-JP',{maximumFractionDigits:2})}兆円`;
  if (a>=1e8) return `${sign}${(a/1e8).toLocaleString('ja-JP',{maximumFractionDigits:1})}億円`;
  if (a>=1e4) return `${sign}${(a/1e4).toLocaleString('ja-JP',{maximumFractionDigits:0})}万円`;
  return `${n.toLocaleString('ja-JP')}円`;
}
function num(value, unit='') {
  return value==null?'—':`${Number(value).toLocaleString('ja-JP',{maximumFractionDigits:1})}${unit}`;
}
function neg(value) { return Number(value)<0?'negative':''; }
function isBank(company){return company.industry33==='銀行業';}
function isInsurance(company){return company.industry33==='保険業';}
function revenueMetric(company, metrics){
  return isBank(company)?metrics.ordinaryRevenue:isInsurance(company)?(metrics.insuranceRevenue??metrics.ordinaryRevenue):metrics.revenue;
}
function revenueLabel(company){return isBank(company)?'経常収益':isInsurance(company)?'保険収益':'売上高';}
function profitMetric(company, metrics){
  return isBank(company)?metrics.ordinaryIncome:isInsurance(company)?metrics.profitBeforeTax:metrics.operatingIncome;
}
function profitLabel(company){return isBank(company)?'経常利益':isInsurance(company)?'税引前利益':'営業利益';}
function scriptJson(value){return JSON.stringify(value).replaceAll('<','\\u003c');}
function renderKpis(company, latest) {
  if (!latest) return `<div class="card kpi"><div class="kpi-label">市場</div><div class="kpi-value">${esc(company.market)}</div><div class="kpi-sub">JPX公式一覧</div></div>
    <div class="card kpi"><div class="kpi-label">業種</div><div class="kpi-value" style="font-size:16px">${esc(company.industry33||'—')}</div><div class="kpi-sub">東証33業種</div></div>
    <div class="card kpi"><div class="kpi-label">EDINET</div><div class="kpi-value" style="font-size:18px">${esc(company.edinetCode||'未対応')}</div><div class="kpi-sub">金融庁コード</div></div>
    <div class="card kpi"><div class="kpi-label">連結財務</div><div class="kpi-value" style="font-size:18px">${company.consolidatedAvailable===true?'あり':company.consolidatedAvailable===false?'なし':'—'}</div><div class="kpi-sub">EDINETコードリスト</div></div>`;
  const m=latest.metrics||{}, revenue=revenueMetric(company,m), profit=profitMetric(company,m);
  const sub=(isBank(company)||isInsurance(company))?`ROE ${num(m.roe,'%')}`:`営業利益率 ${num(m.operatingMargin,'%')}`;
  return `<div class="card kpi"><div class="kpi-label">${revenueLabel(company)}</div><div class="kpi-value ${neg(revenue)}">${esc(money(revenue))}</div><div class="kpi-sub">${esc(latest.periodEnd||'')}</div></div>
    <div class="card kpi"><div class="kpi-label">${profitLabel(company)}</div><div class="kpi-value ${neg(profit)}">${esc(money(profit))}</div><div class="kpi-sub">${esc(sub)}</div></div>
    <div class="card kpi"><div class="kpi-label">当期純利益</div><div class="kpi-value ${neg(m.netIncome)}">${esc(money(m.netIncome))}</div><div class="kpi-sub">ROE ${esc(num(m.roe,'%'))}</div></div>
    <div class="card kpi"><div class="kpi-label">総資産</div><div class="kpi-value">${esc(money(m.assets))}</div><div class="kpi-sub">自己資本比率 ${esc(num(m.equityRatio,'%'))}</div></div>`;
}
function mini(label,value){return `<div class="mini"><span>${esc(label)}</span><b class="${neg(value)}">${esc(money(value))}</b></div>`;}
function fact(label,value){return `<div class="fact"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;}
function seoTitle(company, latest){const salary=latest?.metrics?.averageSalary!=null?'・年収':'';return `${company.name}（${company.securityCode}）の業績${salary}・財務分析 | DATLUME`;}
function seoDescription(company, latest, financials){
  const years=financials.length;
  const span=years>=2?`最大${years}期の業績推移、`:'';
  const salary=latest?.metrics?.averageSalary!=null?'・平均年収':'';
  return `${company.name}（${company.securityCode}）の企業分析。${span}${revenueLabel(company)}・${profitLabel(company)}・純利益・ROE・総資産・キャッシュフロー${salary}をEDINET有価証券報告書から可視化。開示がある場合はセグメント・主要株主も掲載し、同業他社と比較できます。`;
}
function renderSeoSummary(company, latest, financials){
  if(!latest) return `<section class="section card section-card"><div class="section-head"><h2>${esc(company.name)}の企業概要</h2></div><p>${esc(company.name)}は${esc(company.market)}上場、東証33業種では${esc(company.industry33||'業種未設定')}に分類される企業です。このページではJPXとEDINETの公式公開データを使い、確認できた企業情報だけを掲載しています。</p></section>`;
  const m=latest.metrics||{}, revenue=revenueMetric(company,m), profit=profitMetric(company,m);
  const bits=[];
  if(revenue!=null) bits.push(`${revenueLabel(company)}は${money(revenue)}`);
  if(profit!=null) bits.push(`${profitLabel(company)}は${money(profit)}`);
  if(m.netIncome!=null) bits.push(`当期純利益は${money(m.netIncome)}`);
  if(m.assets!=null) bits.push(`総資産は${money(m.assets)}`);
  if(m.averageSalary!=null) bits.push(`平均年間給与は${money(m.averageSalary)}`);
  const first=financials[0]?.periodEnd, last=financials.at(-1)?.periodEnd;
  const range=financials.length>=2&&first&&last?`${first}から${last}まで${financials.length}期分の推移を確認できます。`:'';
  return `<section class="section card section-card"><div class="section-head"><h2>${esc(company.name)}の最新業績・企業概要</h2><p>${esc(latest.periodEnd||'')}</p></div><p>${esc(company.name)}は${esc(company.market)}上場、東証33業種では${esc(company.industry33||'業種未設定')}に分類されます。最新の有価証券報告書では、${esc(bits.join('、')||'主要財務指標を確認できます')}。${esc(range)}</p><p>DATLUMEでは売上・利益だけでなく、資産・負債、キャッシュフロー、従業員数、平均年齢、平均勤続年数、平均年収を同じページで確認できます。開示がある企業ではセグメント別の収益性と主要株主も掲載し、同業種ページや企業比較から他社との違いを確認できます。</p><p class="source">確認できる項目：業績 / 収益性 / 財政状態 / キャッシュフロー / 従業員 / 平均年収 / セグメント / 主要株主 / 同業比較</p></section>`;
}
function structuredData(company, latest, canonical, title, description){
  const corpId=`${canonical}#company`, pageId=`${canonical}#webpage`;
  return {
    '@context':'https://schema.org',
    '@graph':[
      {'@type':'WebSite','@id':'https://datlume.com/#website',url:'https://datlume.com/',name:'DATLUME',inLanguage:'ja'},
      {'@type':'Corporation','@id':corpId,name:company.name,url:canonical,tickerSymbol:`TYO:${company.securityCode}`,identifier:company.securityCode,industry:company.industry33||undefined},
      {'@type':'WebPage','@id':pageId,url:canonical,name:title,description,inLanguage:'ja',isPartOf:{'@id':'https://datlume.com/#website'},mainEntity:{'@id':corpId}},
      {'@type':'BreadcrumbList',itemListElement:[
        {'@type':'ListItem',position:1,name:'DATLUME',item:'https://datlume.com/'},
        {'@type':'ListItem',position:2,name:'上場企業',item:'https://datlume.com/listed-companies/'},
        {'@type':'ListItem',position:3,name:company.name,item:canonical}
      ]}
    ]
  };
}

function renderFinancialSections(company, latest, financials) {
  if (!latest) return `<div class="notice"><b>財務データはまだこの企業ページに連携されていません。</b><br>会社情報を推測で埋めず、EDINETの原データを取得・検証できた項目だけ表示します。</div>`;
  const m=latest.metrics||{}, segments=latest.segments||[], holders=latest.majorShareholders||[];
  const treemap=segments.length>=2?`<section class="section card section-card"><div class="section-head"><div><h2>事業別の稼ぐ力</h2><p>面積＝セグメント売上、濃さ＝営業利益率。XBRLで正式名称と数値を確認できた企業のみ表示。</p></div><p>${esc(latest.periodEnd||'')}</p></div><div id="segment-treemap" class="chart"></div></section>`:'';
  const timeline=financials.length?`<section class="section card section-card"><div class="section-head"><div><h2>10年の業績推移</h2></div><p>${revenueLabel(company)}（棒） / ${profitLabel(company)}（線）</p></div><div id="financial-timeline" class="chart"></div></section>`:'';
  const balance=`<section class="section two"><div class="card section-card"><div class="section-head"><h2>資産と負債</h2><p>最新年度</p></div><div class="mini-grid">${mini('総資産',m.assets)}${mini('負債',m.liabilities)}${mini('純資産',m.equity)}${mini('現預金',m.cash)}</div></div><div class="card section-card"><div class="section-head"><h2>キャッシュフロー</h2><p>最新年度</p></div><div class="mini-grid">${mini('営業CF',m.operatingCashFlow)}${mini('投資CF',m.investingCashFlow)}${mini('財務CF',m.financingCashFlow)}${mini('FCF',m.freeCashFlow)}</div></div></section>`;
  const work=`<section class="section card section-card"><div class="section-head"><div><h2>働くデータ</h2></div><p>有価証券報告書に会社別で開示された値のみ</p></div><div class="facts">${fact('従業員数',num(m.employees,'人'))}${fact('平均年間給与',money(m.averageSalary))}${fact('平均年齢',num(m.averageAge,'歳'))}${fact('平均勤続年数',num(m.averageTenure,'年'))}</div></section>`;
  const ownership=holders.length?`<section class="section card section-card"><div class="section-head"><div><h2>主要株主ネットワーク</h2><p>有価証券報告書の主要株主と持株比率。上場企業として一意に照合できた株主は企業ページへ移動できます。</p></div><p>${esc(latest.periodEnd||'')}</p></div><div id="ownership-network" class="chart"></div><p class="source">線の太さ＝持株比率。上場企業マスタと一意に対応しない株主は名称のみ表示します。子会社・系列関係は検証済みデータが揃うまで混在させません。</p></section>`:'';
  return treemap+timeline+balance+work+ownership;
}

function renderCompany(item) {
  const company=item.company, financials=item.financials||[], latest=item.latest, metrics=latest?.metrics||{};
  const chartRows=financials.map(r=>({
    periodEnd:r.periodEnd,
    revenue:revenueMetric(company,r.metrics||{}),
    profit:profitMetric(company,r.metrics||{})
  }));
  const chartPayload={rows:chartRows,revenueLabel:revenueLabel(company),profitLabel:profitLabel(company),segments:latest?.segments||[],shareholders:latest?.majorShareholders||[],companyName:company.name,companyCode:company.securityCode};
  const industryUrl=company.industry33?`/listed-companies/industries/${encodeURIComponent(company.industry33)}/`:'/listed-companies/';
  const canonical=`https://datlume.com/listed-companies/${company.securityCode}/`;
  const title=seoTitle(company,latest), description=seoDescription(company,latest,financials);
  const robots=latest?'index,follow':'noindex,follow';
  const ld=structuredData(company,latest,canonical,title,description);
  return `<!doctype html><html lang="ja"><head><link rel="icon" type="image/svg+xml" href="/favicon.svg"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="description" content="${esc(description)}"><meta name="robots" content="${robots}"><link rel="canonical" href="${esc(canonical)}"><meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}"><meta property="og:type" content="website"><meta property="og:url" content="${esc(canonical)}"><meta property="og:site_name" content="DATLUME"><meta name="twitter:card" content="summary"><script type="application/ld+json">${scriptJson(ld)}</script><link rel="stylesheet" href="/listed-company.css"><title>${esc(title)}</title></head><body>
<header><div class="wrap"><nav class="nav"><a class="brand" href="/"><img src="/favicon.svg" alt="DATLUME" width="24" height="24" style="filter:brightness(0) invert(1)"><span style="font-size:19px;font-weight:750;letter-spacing:.16em">DATLUME</span></a><div class="navlinks"><a href="/listed-companies/">企業検索</a><a href="/listed-companies/compare/">企業比較</a><a href="/business-industry/">企業・産業</a><a href="/about-data/">データについて</a></div></nav><div class="crumb"><a href="/listed-companies/">上場企業</a> / <a href="${esc(industryUrl)}">${esc(company.industry33||'業種未設定')}</a></div><div class="hero"><div><span class="code">${esc(company.securityCode)}</span><h1>${esc(company.name)}</h1><p>${esc(company.market)} · ${esc(company.industry33||'業種未設定')}${company.edinetNameEn?` · ${esc(company.edinetNameEn)}`:''}</p></div><div class="hero-side"><b>${esc(company.fiscalYearEnd||'決算期未確認')}</b><span>決算期 · EDINET ${esc(company.edinetCode||'未対応')}</span></div></div></div></header>
<main class="wrap"><section class="overview">${renderKpis(company,latest)}</section>
${renderSeoSummary(company,latest,financials)}
${renderFinancialSections(company,latest,financials)}
<section class="section two"><a class="card link-card" href="/listed-companies/compare/?codes=${esc(company.securityCode)}"><b>この企業を比較に追加</b><span>2〜5社を同じ尺度で横並び比較します。</span><div class="open">企業比較へ →</div></a><a class="card link-card" href="${esc(industryUrl)}"><b>${esc(company.industry33||'同業種')}の企業を比較</b><span>同じ業種の企業を一覧・財務指標で比較します。</span><div class="open">同業比較へ →</div></a><a class="card link-card" href="/business-industry/"><b>地域の産業構造を見る</b><span>企業1社ではなく、都道府県ごとの産業集積を見る。</span><div class="open">企業・産業へ →</div></a></section>
<section class="section card section-card source"><div class="section-head"><h2>出典とデータ品質</h2></div><p>企業マスタ：日本取引所グループ「東証上場銘柄一覧」＋金融庁「EDINETコードリスト」。財務：EDINET 有価証券報告書のXBRL/CSV。原則として連結財務を優先し、連結がない場合のみ個別財務を使用します。</p>${latest?`<p>最新参照書類：<code>${esc(latest.docID)}</code> · 提出 ${esc(latest.submitDateTime||'—')} · 会計基準 ${esc(latest.accountingStandard||'未判定')} · 形式 ${esc(latest.sourceFormat||'—')}</p>`:''}<p>金融業は一般企業と財務構造が異なるため、負債比率・営業利益率などを同じ意味で評価しません。欠損値や未取得値を推測で補完しません。</p></section>
</main><footer><div class="wrap">DATLUME · 日本企業分析 · <a href="/listed-companies/">企業一覧に戻る</a> · <a href="/privacy/">プライバシーポリシー</a></div></footer>
<script type="application/json" id="financial-data">${scriptJson(chartPayload)}</script><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script><script src="/listed-company.js"></script></body></html>`;
}

async function handle(context, headOnly=false) {
  const code=String(context.params.code||'').toUpperCase();
  if(!/^[0-9A-Z]{4}$/.test(code)) return new Response('Not Found',{status:404,headers:SECURITY_HEADERS});
  const item=await loadCompany(context,code);
  if(!item) return new Response('Not Found',{status:404,headers:SECURITY_HEADERS});
  return new Response(headOnly?null:renderCompany(item),{
    status:200,
    headers:{...SECURITY_HEADERS,'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=3600, stale-while-revalidate=86400'}
  });
}

export function onRequestGet(context){return handle(context,false);}
export function onRequestHead(context){return handle(context,true);}
