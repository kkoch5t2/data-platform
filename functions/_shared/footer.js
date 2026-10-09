// Shared navigation for static Astro pages and Pages Functions.
export const footerLinks = `<nav class="datlume-footer-links" aria-label="フッターリンク"><a href="https://github.com/kkoch5t2/data-platform" target="_blank" rel="noreferrer"><img src="/brand/github.svg" alt="" width="14" height="14">GitHub ↗</a><a href="https://utility-tools-jp.com/" target="_blank" rel="noreferrer"><img class="utility-icon" src="/brand/utility-tools.ico" alt="" width="14" height="14">無料WEB便利ツール集 ↗</a><a href="/privacy/">プライバシーポリシー</a></nav>`;
export function renderFooter(notes = 'DATLUME — 日本の公開データを、比較できる形に。') {
  return `<footer class="datlume-footer"><div class="datlume-footer-inner"><div class="datlume-footer-description">${notes}</div>${footerLinks}</div></footer>`;
}
