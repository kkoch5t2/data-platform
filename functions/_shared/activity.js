const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;");
function sourceLink(url) {
  try {
    const value = new URL(String(url || ''));
    return value.protocol === 'https:' && ['www.j-platpat.inpit.go.jp','j-platpat.inpit.go.jp'].includes(value.hostname) ? value.href : null;
  } catch { return null; }
}
function subsidyCard(data, sourceDate) {
  if (!data?.count) return '';
  const rows = (data.recent || []).map(item => `<li><div><b>${esc(item.name)}</b><small>${esc(item.issuer || '発行元の記載なし')} · ${esc(item.date || '日付の記載なし')}</small></div><strong>${item.amount == null ? '金額の記載なし' : esc(Number(item.amount).toLocaleString('ja-JP') + '円')}</strong></li>`).join('');
  return `<section class="activity-panel"><div class="activity-head"><h2>補助金の記録</h2><span>${Number(data.count).toLocaleString('ja-JP')}件</span></div><p>Gビズインフォに掲載された、この法人番号の記録です。直近の最大8件を表示。</p><ul>${rows}</ul><p class="activity-source">データ取得元：<a href="https://info.gbiz.go.jp/hojin/DownloadTop" target="_blank" rel="noreferrer">Gビズインフォ</a> · 配布日 ${esc(sourceDate || '不明')}。金額は記録ごとの記載値です。</p></section>`;
}
function patentCard(data, sourceDate) {
  if (!data?.count) return '';
  const rows = (data.recent || []).map(item => {
    const url = sourceLink(item.url);
    const name = esc(item.name || '名称の記載なし');
    return `<li><div><b>${url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${name}</a>` : name}</b><small>登録番号 ${esc(item.registration)} · 出願 ${esc(item.applicationDate || '日付の記載なし')}</small></div></li>`;
  }).join('');
  return `<section class="activity-panel"><div class="activity-head"><h2>特許の記録</h2><span>${Number(data.count).toLocaleString('ja-JP')}件</span></div><p>同じ登録番号の分類行をまとめた件数です。直近の最大8件を出願日順に表示。</p><ul>${rows}</ul><p class="activity-source">データ取得元：<a href="https://info.gbiz.go.jp/hojin/DownloadTop" target="_blank" rel="noreferrer">Gビズインフォ</a> · 配布日 ${esc(sourceDate || '不明')}。登録日や現在の権利状態を示す件数ではありません。</p></section>`;
}
export function renderActivity(activity) {
  if (!activity?.subsidies && !activity?.patents) return '';
  return `<section class="activity-wrap">${subsidyCard(activity.subsidies, activity.subsidies?.sourceDate)}${patentCard(activity.patents, activity.patents?.sourceDate)}</section>`;
}
