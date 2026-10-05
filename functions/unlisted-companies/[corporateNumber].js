import { renderWorkplace } from '../_shared/workplace.js';
import { renderActivity } from '../_shared/activity.js';
const SECURITY_HEADERS={
  'X-Content-Type-Options':'nosniff','Referrer-Policy':'strict-origin-when-cross-origin',
  'X-Frame-Options':'SAMEORIGIN','Permissions-Policy':'geolocation=(), camera=(), microphone=()'
};
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');}
function safeUrl(v){try{const u=new URL(String(v||''));return ['https:','http:'].includes(u.protocol)?u.href:'#'}catch{return '#'}}
function fmt(v){return Number(v||0).toLocaleString('ja-JP');}
function money(v){if(v==null)return'—';const n=Number(v),a=Math.abs(n),s=n<0?'-':'';if(a>=1e12)return`${s}${(a/1e12).toLocaleString('ja-JP',{maximumFractionDigits:2})}兆円`;if(a>=1e8)return`${s}${(a/1e8).toLocaleString('ja-JP',{maximumFractionDigits:1})}億円`;if(a>=1e4)return`${s}${(a/1e4).toLocaleString('ja-JP',{maximumFractionDigits:0})}万円`;return`${n.toLocaleString('ja-JP')}円`;}
async function detailBucket(key){const hash=await crypto.subtle.digest('SHA-1',new TextEncoder().encode(key));return(new DataView(hash).getUint32(0,false)%64).toString(16).padStart(2,'0');}
async function loadNameGroup(context,name){
  const url=new URL('/data/company-registry/name-groups.json',context.request.url);
  const res=await context.env.ASSETS.fetch(url);
  if(!res.ok)return null;
  const data=await res.json();
  const normalized=String(name||'').normalize('NFKC').replace(/\s/g,'').toLowerCase();
  return (data.records||[]).find(row=>/^co_[0-9a-f]{12}$/.test(row.companyId||'')&&
    String(row.name||'').normalize('NFKC').replace(/\s/g,'').toLowerCase()===normalized)||null;
}
async function loadEntity(context,corporateNumber){const bucket=await detailBucket(corporateNumber);const url=new URL(`/data/company-registry/details/${bucket}.json`,context.request.url);const res=await context.env.ASSETS.fetch(url);if(!res.ok)return null;const data=await res.json();return data?.c?.[corporateNumber]||null;}
async function loadProcurementRows(context,companyIds,sourceIds){const rows=[],allowed=new Set(sourceIds||[]);for(const id of companyIds||[]){if(!/^co_[0-9a-f]{12}$/.test(id))continue;const bucket=id.slice(3,5).toLowerCase();const url=new URL(`/data/company-details/${bucket}.json`,context.request.url);const res=await context.env.ASSETS.fetch(url);if(!res.ok)continue;const data=await res.json();const item=data?.c?.[id];if(item?.[3])rows.push(...item[3].filter(row=>allowed.has(row[5])));}return rows.sort((a,b)=>String(b[0]||'').localeCompare(String(a[0]||'')));}
function address(entity){const n=entity.nta||{};return [n.prefecture,n.city,n.street].filter(Boolean).join('')||'—';}
function renderAgencyBars(rows){const map=new Map();for(const r of rows)map.set(r[1],(map.get(r[1])||0)+Number(r[4]||0));const top=[...map.entries()].sort((a,b)=>b[1]-a[1]).slice(0,8),max=Math.max(...top.map(([,v])=>v),1);return top.map(([name,value])=>`<div class="barrow"><div>${esc(name)}</div><div class="track"><div class="bar" style="width:${Math.max(2,value/max*100).toFixed(1)}%"></div></div><b>${esc(money(value))}</b></div>`).join('');}
function renderTable(rows){if(!rows.length)return'<div class="empty">この法人への帰属を確認できた、金額付き調達案件はありません。</div>';const visible=20,shown=rows.slice(0,60);const body=shown.map((r,i)=>`<tr${i>=visible?' hidden data-extra-row':''}><td>${esc(r[0]||'—')}</td><td>${esc(r[1]||'—')}</td><td class="title"><a href="${esc(safeUrl(r[3]))}" target="_blank" rel="noreferrer">${esc(r[2]||'—')}</a></td><td>${esc(money(r[4]))}</td></tr>`).join('');const more=shown.length>visible?`<button class="more-btn" type="button" data-show-more>さらに${shown.length-visible}件を表示</button>`:'';return`<div class="table-wrap"><table><thead><tr><th>落札日</th><th>発注機関</th><th>案件</th><th>金額</th></tr></thead><tbody>${body}</tbody></table></div>${more}`;}
function financeAmount(v,u){if(v==null)return'—';if(!u||u==='JPY')return money(v);if(u==='pure')return fmt(v);return `${fmt(v)} ${u}`;}
function pct(v){return v==null?'—':`${Number(v).toLocaleString('ja-JP',{maximumFractionDigits:2})}%`;}
function negativeClass(v){return v!=null&&Number(v)<0?' negative':'';}
function financeMetric(label,value,unit='JPY'){return `<div class="finance-metric"><span>${esc(label)}</span><b class="${negativeClass(value).trim()}">${esc(financeAmount(value,unit))}</b></div>`;}
function financeTextMetric(label,value){return `<div class="finance-metric"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;}
function financePctMetric(label,value){return `<div class="finance-metric"><span>${esc(label)}</span><b class="${negativeClass(value).trim()}">${esc(pct(value))}</b></div>`;}
function financeGroup(title,content){return `<div class="finance-group"><div class="finance-group-head"><h3>${esc(title)}</h3><span>最新収録期</span></div><div class="finance-card-grid">${content}</div></div>`;}
function renderFinanceSummary(entity){
  const f=entity.finance,ps=f?.periods||[];
  if(!ps.length)return'<div class="finance-empty"><b>公開財務は未収録です</b><p>gBizINFO・決算公告など、公式に取得・検証できた情報だけを追加します。売上や利益を推測で補完しません。</p></div>';
  const a=f.analysis||{},latest=ps[0]||{},legacy=f.snapshotStatus==='legacy',statement=f.datasetType==='statements';
  const sourceLabel=f.sourceLabel||(legacy?'旧gBizINFOスナップショット':'gBizINFO 財務情報');
  const sourceNote=legacy?'最新データではありません':(statement?'官報決算公告の要旨':'現行配布データ');
  const source=`<div class="finance-source-line"><div><b>${esc(sourceLabel)}</b><span>${esc(sourceNote)}</span></div><time>${esc(f.sourceDate||'—')}時点</time></div>`;
  if(statement){
    const equityValue=latest.netAssets??latest.shareholdersEquity;
    const equityLabel=latest.netAssets!=null?'純資産':'株主資本';
    const balance=financeGroup('資産と負債',
      financeMetric('総資産',latest.totalAssets,latest.totalAssetsUnit)+
      financeMetric(equityLabel,equityValue,'JPY')+
      financeMetric('流動負債',latest.currentLiabilities,'JPY')+
      financeMetric('固定負債',latest.fixedLiabilities,'JPY'));
    const performance=financeGroup('資本・損益',
      financeMetric('資本金',latest.capitalStock,latest.capitalStockUnit||'JPY')+
      financeMetric(a.primaryRevenueLabel||'売上系指標',a.primaryRevenue,a.primaryRevenueUnit)+
      financeMetric('経常利益 / 損失',a.ordinaryIncomeLoss,'JPY')+
      financeMetric('当期純利益 / 損失',a.netIncomeLoss,a.netIncomeLossUnit));
    return `${source}${balance}${performance}<p class="finance-period">最新収録期：${esc(latest.periodLabel||latest.fiscalYear||'期間記載なし')}</p>`;
  }
  const performance=financeGroup('業績',
    financeMetric(a.primaryRevenueLabel||'売上系指標',a.primaryRevenue,a.primaryRevenueUnit)+
    financeMetric('経常利益 / 損失',a.ordinaryIncomeLoss,'JPY')+
    financeMetric('当期純利益 / 損失',a.netIncomeLoss,a.netIncomeLossUnit)+
    financePctMetric('売上系 前期比',a.revenueGrowthPct));
  const position=financeGroup('資産・人員',
    financeMetric('総資産',a.totalAssets,a.totalAssetsUnit)+
    financeMetric('純資産',a.netAssets,a.netAssetsUnit)+
    financeMetric('資本金',a.capitalStock,'JPY')+
    financeTextMetric('従業員数',a.employees==null?'—':`${fmt(a.employees)}人`));
  return `${source}${performance}${position}<p class="finance-period">最新収録期：${esc(latest.fiscalYear||'期間記載なし')}</p>`;
}
function renderFinanceHistory(entity){
  const f=entity.finance,ps=f?.periods||[];
  if(!ps.length)return'';
  const statement=f.datasetType==='statements';
  const cards=ps.map((p,i)=>{
    const equityValue=p.netAssets??p.shareholdersEquity;
    const equityLabel=p.netAssets!=null?'純資産':'株主資本';
    const metrics=statement?
      financeMetric('総資産',p.totalAssets,p.totalAssetsUnit)+financeMetric(equityLabel,equityValue,'JPY')+financeMetric('資本金',p.capitalStock,p.capitalStockUnit||'JPY')+financeMetric('当期純利益 / 損失',p.netIncomeLoss,p.netIncomeLossUnit):
      financeMetric(p.primaryRevenueLabel||'売上系指標',p.primaryRevenue,p.primaryRevenueUnit)+financeMetric('経常利益 / 損失',p.ordinaryIncomeLoss,p.ordinaryIncomeLossUnit)+financeMetric('当期純利益 / 損失',p.netIncomeLoss,p.netIncomeLossUnit)+financeMetric('総資産',p.totalAssets,p.totalAssetsUnit);
    const period=statement?(p.periodLabel||p.fiscalYear||`第${i+1}期`):(i===0?'最新期':`${i}期前`);
    const date=statement?(p.balanceDate||p.releaseDate||''):(i===0?(p.fiscalYear||'最新収録期'):`回次 ${i}`);
    return `<article class="finance-period-card${i===0?' latest':''}"><div class="finance-period-head"><div><span>${i===0?'最新':'履歴'}</span><h3>${esc(period)}</h3></div><time>${esc(date)}</time></div><div class="period-metric-grid">${metrics}</div></article>`;
  });
  const latestCard=cards[0]||'';
  const olderCards=cards.slice(1);
  const historyLabel=statement?`過去${olderCards.length}期の決算公告を見る`:`過去${olderCards.length}期の推移を見る`;
  const historyCloseLabel=`過去${olderCards.length}期を閉じる`;
  const historyMore=olderCards.length?`<details class="finance-history-more"><summary><span class="history-label history-label-closed">${esc(historyLabel)}</span><span class="history-label history-label-open">${esc(historyCloseLabel)}</span><span class="history-chevron" aria-hidden="true">⌄</span></summary><div class="finance-period-grid finance-period-grid-past">${olderCards.join('')}</div></details>`:'';
  const source=f.sourceUrl?`<a href="${esc(safeUrl(f.sourceUrl))}" target="_blank" rel="noreferrer">gBizINFO公式配布元</a>`:'gBizINFO';
  const note=statement?'最新の決算公告を表示しています。過去分は必要なときだけ展開できます。公告にない項目は推測せず「—」とします。':'最新の公開財務を表示しています。過去回次は必要なときだけ展開でき、年度はDATLUME側で推測して付与しません。';
  return `<section class="section card panel finance-history-panel"><div class="section-head"><div><h2>${statement?'決算公告の推移':'財務データの推移'}</h2><p>${esc(note)}</p></div><p>${esc(f.sourceDate||'')}時点 · ${source}</p></div><div class="finance-period-grid finance-period-grid-latest">${latestCard}</div>${historyMore}</section>`;
}
function renderProcurementStats(p){
  if(!p.awardCount)return'';
  return `<section class="stats proc-stats"><div class="card stat"><span>受注額</span><b>${esc(money(p.awardTotal))}</b><small>この会社と確認できた案件</small></div><div class="card stat"><span>案件数</span><b>${esc(fmt(p.awardCount))}件</b><small>公開元の記録から確認</small></div></section>`;
}
function renderProcurementSections(p,rows,nameGroup){
  if(!p.awardCount){const href=nameGroup?`/procurement/companies/${nameGroup.companyId}/`:'/unlisted-companies/';const label=nameGroup?'同じ企業名で掲載された案件を見る →':'受注企業名のランキングを見る →';return `<section class="section card panel"><div class="section-head"><h2>公共調達</h2></div><p class="plain-note">この会社の受注と確認できた案件は、まだ掲載していません。</p><p class="plain-note"><a href="${href}">${label}</a></p></section>`;}
  return `<section class="section card panel"><div class="section-head"><h2>主な発注機関</h2></div><div class="bars">${renderAgencyBars(rows)}</div></section>
<section class="section card panel"><div class="section-head"><h2>公共調達の案件</h2><p>最新60件まで表示</p></div>${renderTable(rows)}</section>`;
}
function render(entity,rows,nameGroup){const n=entity.nta||{},p=entity.procurement||{},canonical=`https://datlume.com/unlisted-companies/${entity.corporateNumber}/`;const description=p.awardCount?`${entity.name}の基本情報と公開されている調達実績を確認できます。`:`${entity.name}の基本情報を確認できます。`;const aliases=(p.aliases||[]).filter(x=>x&&x!==entity.name);const title=`${entity.name}｜未上場企業情報 | DATLUME`;return`<!doctype html><html lang="ja"><head><link rel="icon" type="image/svg+xml" href="/favicon.svg"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="description" content="${esc(description)}"><link rel="canonical" href="${esc(canonical)}"><meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}"><meta property="og:type" content="website"><meta name="twitter:card" content="summary"><link rel="stylesheet" href="/unlisted-company.css"><title>${esc(title)}</title><link rel="stylesheet" href="/workplace.css"><link rel="stylesheet" href="/activity.css"></head><body>
<header><div class="wrap"><nav><a class="brand" href="/"><img src="/favicon.svg" alt="" width="24" height="24"><span>DATLUME</span></a><div class="navlinks"><a href="/unlisted-companies/">未上場企業</a><a href="/listed-companies/">上場企業</a><a href="/procurement/">公共調達</a><a href="/about-data/">データについて</a></div></nav><div class="crumb"><a href="/unlisted-companies/">未上場企業</a> / 法人番号 ${esc(entity.corporateNumber)}</div><div class="hero"><div><div class="eyebrow">UNLISTED COMPANY</div><h1>${esc(entity.name)}</h1><p>${esc(n.prefecture||'所在地未確認')} ${esc(n.city||'')} · 法人番号 ${esc(entity.corporateNumber)}</p></div><div class="status">現存する会社<br><span>未上場として掲載</span></div></div></div></header>
<main class="wrap">${renderProcurementStats(p)}
<section class="section card panel basic-panel"><div class="section-head"><h2>法人基本情報</h2><p>国税庁 法人番号公表サイト</p></div><div class="facts"><div><span>法人番号</span><b>${esc(entity.corporateNumber)}</b></div><div><span>所在地</span><b>${esc(address(entity))}</b></div><div><span>法人番号指定日</span><b>${esc(n.assignmentDate||'—')}</b></div><div><span>最終更新日</span><b>${esc(n.updateDate||'—')}</b></div>${n.furigana?`<div><span>フリガナ</span><b>${esc(n.furigana)}</b></div>`:''}${aliases.length?`<div><span>調達データ上の名称</span><b>${esc(aliases.slice(0,4).join(' / '))}</b></div>`:''}</div></section>
<section class="section card panel finance-panel"><div class="section-head"><div><h2>財務データ</h2><p>公開元で確認できた値だけを表示</p></div><p>${entity.finance?.periods?.length?`${esc(entity.finance.periods.length)}期収録`:`未収録`}</p></div>${renderFinanceSummary(entity)}</section>${renderFinanceHistory(entity)}
${renderProcurementSections(p,rows,nameGroup)}
${renderWorkplace(entity.workplace)}
${renderActivity(entity.activity)}
<section class="section card panel source"><div class="section-head"><h2>出典と判定方法</h2></div><p>法人基本情報は国税庁「法人番号公表サイト」の全国全件データを使用しています。未上場判定は、現存する会社形態（株式会社・有限会社・合名会社・合資会社・合同会社）に限定し、日本取引所グループの東証上場銘柄一覧と金融庁EDINETコードリストの上場区分を除外しています。</p><p>この法人に結び付けた調達実績は、受注者欄と法人番号を同じ千葉市の公式案件で確認し、国税庁の法人名とも照合した案件だけです。社名の一致だけで法人に結び付けた案件は含みません。受注額は企業の売上高ではありません。</p><p>財務はgBizINFOの財務情報、および決算情報に収録された官報決算公告の要旨を法人番号で照合しています。公告に記載のない売上・利益等は推測で補完しません。</p></section>
</main><footer><div class="wrap">DATLUME · <a href="/unlisted-companies/">未上場企業一覧に戻る</a> · <a href="/about-data/">データについて</a> · <a href="/privacy/">プライバシーポリシー</a></div></footer><script>{const b=document.querySelector('[data-show-more]');b?.addEventListener('click',()=>{const rs=[...document.querySelectorAll('[data-extra-row]')],expanded=b.dataset.expanded==='1';rs.forEach(r=>r.hidden=expanded);b.dataset.expanded=expanded?'0':'1';b.textContent=expanded?'さらに'+rs.length+'件を表示':'20件に戻す'})}</script></body></html>`;}
async function handle(context,headOnly=false){const corporateNumber=String(context.params.corporateNumber||'');if(!/^\d{13}$/.test(corporateNumber))return new Response('Not Found',{status:404,headers:SECURITY_HEADERS});const entity=await loadEntity(context,corporateNumber);if(!entity||entity.unlistedEligible!==true)return new Response('Not Found',{status:404,headers:SECURITY_HEADERS});const rows=await loadProcurementRows(context,entity.procurement?.companyIds||[],entity.procurement?.sourceIds||[]);const nameGroup=!headOnly&&!entity.procurement?.awardCount?await loadNameGroup(context,entity.name):null;return new Response(headOnly?null:render(entity,rows,nameGroup),{status:200,headers:{...SECURITY_HEADERS,'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=3600, stale-while-revalidate=86400'}});}
export function onRequestGet(context){return handle(context,false)}
export function onRequestHead(context){return handle(context,true)}
