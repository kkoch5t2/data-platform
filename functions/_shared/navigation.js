// One navigation definition for Astro pages and Pages Functions.
export const dataSections = [
 ['🏛️','国・自治体の案件','/procurement/'],['🏠','不動産・暮らし','/realestate/'],
 ['🗾','都道府県別推移','/regional/'],['💼','雇用・賃金','/employment-economy/'],
 ['🏭','企業・産業','/business-industry/'],['🌾','農業・食の産地','/agriculture/'],
 ['📈','上場企業','/listed-companies/'],['🏢','未上場企業','/unlisted-companies/'],
 ['💴','経済・物価','/economy-prices/'],['⚡','エネルギー','/energy/'],['🚆','公共交通','/transport/']
];
// Inline SVG keeps the chevron optically centered across OS/font combinations.
const chevron = `<svg class="datlume-chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="m4 6 4 4 4-4"/></svg>`;
export function renderNavigation(){
 const links=dataSections.map(([icon,label,url])=>`<a href="${url}"><span aria-hidden="true">${icon}</span>${label}</a>`).join('');
 return `<nav class="datlume-nav" aria-label="サイト共通メニュー"><a class="datlume-brand" href="/" aria-label="DATLUME トップページ"><img src="/favicon.svg" alt="" width="24" height="24"><span>DATLUME</span></a><div class="datlume-nav-actions"><details class="datlume-menu"><summary>データを探す${chevron}</summary><div class="datlume-menu-panel datlume-data-panel"><a class="datlume-menu-home" href="/#datasets">すべてのデータを見る →</a>${links}<a href="/topics/"><span aria-hidden="true">🔥</span>話題のトピック</a></div></details><details class="datlume-menu"><summary>サイト情報${chevron}</summary><div class="datlume-menu-panel datlume-info-panel"><a href="/about-data/">📚 データについて</a><a href="/analytics/">📊 サイト統計</a><a href="/privacy/">🔒 プライバシー</a><a href="https://github.com/kkoch5t2/data-platform" target="_blank" rel="noopener noreferrer">GitHub ↗</a></div></details></div></nav>`;
}
