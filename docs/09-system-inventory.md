# DATLUME システム・機能インベントリ

最終更新: 2026-10-09

この文書は、公開領域・主要ソース・collector・更新頻度・主要URLを横断して確認するための索引である。
詳細なソース定義の正本は `collector/source_catalog.json`。

| 領域 | 主な公開URL | 主なソース | 主なcollector | 更新 |
|---|---|---|---|---|
| 公共調達 | `/procurement/` | JETRO / GEPS / 自治体公式 | `collect_jetro.py`、各自治体collector | 日次 |
| 不動産・暮らし | `/realestate/` | 国土数値情報 / ハザードマップ / 警察庁等 | `collect_land_prices.py`、`collect_living_layers.py`、`collect_reinfolib_transactions.py`、`backfill_reinfolib_history.py` | 月次 |
| 都道府県別推移 | `/regional/` | SSDSE / 人口移動報告 | `collect_regional_trends.py` 等 | 月次 |
| 市区町村の将来人口 | `/regional/projections/` | 社人研・2023年推計 | `collect_ipss_population.py` | 月次再確認 |
| 雇用・賃金 | `/employment-economy/` | 賃金構造基本統計 / SSDSE | `collect_employment_economy.py` 等 | 月次 |
| 企業・産業 | `/business-industry/` | SSDSE-E | `collect_business_industry.py` 等 | 月次 |
| 上場企業 | `/listed-companies/` | JPX / EDINET | `collector/listed_companies/*` | 日次 + マスタ月次 |
| 経済・物価 | `/economy-prices/` | 小売物価統計調査 | `collect_economy_prices.py` 等 | 月次 |
| エネルギー | `/energy/` | 家計調査 / SSDSE / 資源エネルギー庁 | `collect_energy.py` 等 | 月次 |

## 公共調達自治体collector
- `collect_yokohama_procurement.py`
- `collect_sapporo_procurement.py`
- `collect_kobe_procurement.py`
- `collect_fukuoka_procurement.py`
- `collect_chiba_procurement.py`
- `collect_kyoto_procurement.py`

## 上場企業パイプライン
- `collect_master.py` — JPX / EDINET企業マスタ
- `collect_documents.py` — EDINET提出書類一覧
- `bulk_download.py` — CSV優先、XBRL fallback付き取得
- `normalize_financials.py` / `normalize_incremental.py` — 財務正規化
- `validate_salary_outliers.py` — 平均年間給与原典再検証
- `segments.py` — セグメント
- `ownership.py` — 主要株主
- `build_public_data.py` — public index/ranking/64 shard生成

## 動的配信
- `functions/listed-companies/[code].js` — 上場企業詳細。
- `functions/procurement/companies/[id].js` — 公共調達企業詳細。
- `public/_routes.json` — Functions対象/除外ルート。

## 共通運用
- `scripts/daily-refresh.sh` — 日次/月次収集からbuild/deployまで。
- `scripts/weekly-audit.sh` — 週次の全体品質監査。
- `scripts/audit-data-integrity.py` — データ整合性。
- `scripts/audit-generated-html.py` — 全静的HTMLとSEO/AdSense前提の監査。
- `scripts/audit-listed-xbrl-samples.py` — EDINET原典監査。
- `scripts/e2e-deep.cjs` — PC/モバイルE2E。
- `scripts/generate-sitemap.py` — 静的＋動的URLのsitemap生成。
- `deploy-datlume.sh` — Cloudflare Pagesデプロイと上限/完全性guard。

## 公開補助ページ
- `/about-data/` — 出典、定義、収録範囲、免責。
- `/privacy/` — Cloudflare Analytics、AdSense、Cookie、CMP、ログ等。
- `/analytics/` — Cloudflare Web Analytics由来のサイト統計。
- `/ads.txt` — AdSense販売者宣言。
- `/sitemap.xml` — 検索エンジン向けURL一覧。

## 変更時の確認先
- 新しいデータソース追加: `collector/source_catalog.json` + `04-data-design.md`
- 新しいページ追加: `src/pages/` + sitemap/HTML監査
- 新しい動的ルート追加: `functions/` + `public/_routes.json` + deploy guard
- 新しいCookie/広告/計測: `/privacy/` + `07-monetization-adsense.md`
- 新しいsecret: `08-security.md` + `.gitignore`/運用ファイル配置


## しょくばらぼ職場情報（2026-10-05追加）
職場情報：collector/collect_shokuba.py、data/raw/shokuba/（原本ZIPとworkplace.sqlite）、既存listed-companies/company-registry詳細shard、functions/_shared/workplace.js、public/workplace.css、scripts/audit-shokuba.py、scripts/test-shokuba.py、scripts/e2e-workplace.cjs。

## Gビズインフォの補助金・特許（2026-10-05追加）
上場・未上場企業詳細に法人番号で追加する。`collect_gbiz_bulk.py` で月次ZIPを取得し、`gbiz_activity.py` が特許の登録番号重複をまとめる。`functions/_shared/activity.js` と `public/activity.css` が表示を担当し、`scripts/audit-gbiz-activity.py` と `scripts/e2e-gbiz-activity.cjs` が原典・PC/モバイルを検査する。

## 宿泊旅行統計（2026-10-05追加）
`/regional/stays/` — 観光庁の月次推移表。`collector/collect_lodging_statistics.py` → `public/data/lodging-statistics.json` → 地域比較・ランキング。月次独立マーカー、`scripts/audit-lodging-statistics.py`、`scripts/e2e-lodging-statistics.cjs`。

## 気象庁・観測所別気象
- 収集：`collector/collect_jma_weather.py`（気象庁過去データのCSV、アメダス観測所一覧 ZIP）。
- 公開：`public/data/weather/index.json` と地方コード別JSON、`/regional/weather/`。
- 更新・監視：`last-jma-weather-refresh`、`jma_weather` source health、`audit-jma-weather.py`。生CSVは `data/raw/weather/`。


## 公共交通データ（2026-10-06追加）

| 項目 | 実装 |
|---|---|
| 公共交通画面 | `src/pages/transport/index.astro`、`src/scripts/transport.ts` |
| 公式データ収集 | `collector/collect_public_transport.py`、ソースID `public_transport` |
| 公開データ | `public/data/transport/index.json`、`stations.json`、`commute.json`、`usage.json` |
| 数値監査 / E2E | `scripts/audit-public-transport.py`、`scripts/e2e-public-transport.cjs` |
| 月次更新 | `last-public-transport-refresh`、`scripts/collect-daily.sh` |

## 農業・食の産地（2026-10-10）
`/agriculture/`（`src/pages/agriculture/index.astro`）、公開JSON `public/data/agriculture-output.json`、収集 `collector/collect_agriculture_output.py`、台帳 `agriculture_output`。トップページのカードとナビから接続する。
