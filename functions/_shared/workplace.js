const escape = v => String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const scopeLabel = v => String(v || '').replace(/^\d+:/,'');
export function renderWorkplace(workplace) {
  if (!workplace || (!Object.keys(workplace.metrics || {}).length && !Object.keys(workplace.hiring || {}).length)) return '';
  const metrics = Object.entries(workplace.metrics || {});
  const cards = metrics.map(([key,m]) => `<div class="workplace-metric" data-metric-key="${escape(key)}"><span>${escape(m.label)}</span><b class="workplace-value">${escape(m.display)}</b>${m.scope ? `<small>対象：${escape(scopeLabel(m.scope))}</small>` : ''}</div>`).join('');
  const notes = metrics.filter(([,m]) => m.note).map(([,m]) => `<div><dt>${escape(m.label)}</dt><dd>${escape(m.note)}</dd></div>`).join('');
  const hiring = Object.entries(workplace.hiring || {}).map(([key,h]) => {
    const row = (field,label) => h[field] ? `<tr data-hiring-key="${escape(key)}-${field}"><th scope="row">${label}</th>${h[field].map(v => `<td>${escape(v.display)}</td>`).join('')}</tr>` : '';
    return `<div class="workplace-hiring"><h3>${escape(h.label)}</h3><div class="workplace-table"><table><thead><tr><th>項目</th><th>前年度</th><th>2年度前</th><th>3年度前</th></tr></thead><tbody>${row('hires','採用人数')}${row('leavers','その採用者の離職人数')}</tbody></table></div></div>`;
  }).join('');
  return `<section class="section card section-card panel workplace-panel" data-corporate-number="${escape(workplace.corporateNumber)}"><div class="section-head"><div><h2>職場の働き方</h2><p>残業・休暇・採用の公開データ</p></div><p>しょくばらぼ</p></div>${cards ? `<div class="workplace-grid">${cards}</div>` : ''}${hiring}${notes ? `<details class="workplace-notes"><summary>対象・期間の補足</summary><dl>${notes}</dl></details>` : ''}<p class="workplace-source">出典：<a href="https://shokuba.mhlw.go.jp/shokuba/utilize/utilize010.do" target="_blank" rel="noreferrer">厚生労働省「しょくばらぼ」</a>のデータを加工して作成。配布データ：${escape(workplace.sourceDate)}<br>企業情報の更新：${escape(workplace.sourceUpdatedAt || '未記載')}。会社が公開した値で、対象・期間は項目によって異なります。採用表の「前年度」は原典の表記です。</p></section>`;
}