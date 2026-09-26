# DATLUME 基本設計書

最終更新: 2026-09-27

## 1. 全体アーキテクチャ
DATLUME は「収集」「正規化・監査」「公開データ生成」「静的ビルド」「動的詳細ページ」「Cloudflare配信」を分離した構成を採る。

```text
公式データ/API/Web
    ↓ Python collectors
Raw / SQLite / normalized data (Ubuntu)
    ↓ build scripts
public/data + src/data
    ↓ Astro build
静的HTML / JSON / JS / CSS (dist)
    ↓ Cloudflare Pages
通常ページは静的配信
    └─ Pages Functions: 上場企業詳細 / 公共調達企業詳細
```

## 2. 技術スタック
- フロント: Astro 7
- グラフ: ECharts 6
- 地図: MapLibre GL JS 6.11.1
- E2E: Playwright
- 収集/正規化: Python 3
- 公共調達保存: SQLite
- 配信: Cloudflare Pages / Pages Functions
- 実行環境: Ubuntu + Node.js 22系

## 3. 配信方式
### 静的ページ
トップ、各領域トップ、ランキング、都道府県、業種、年度、発注機関等はAstroで静的生成する。
静的ページはFunctionsを経由せずCloudflare Pagesのアセットとして配信する。

### 動的ページ
`public/_routes.json` により次だけFunctions対象とする。
- `/listed-companies/{securityCode}/`
- `/procurement/companies/{companyId}/`
一覧・比較・業種ページは明示的にFunctions対象から除外する。

## 4. URL設計
- `/` — 総合入口
- `/procurement/` — 公共調達
- `/realestate/` — 不動産・暮らし
- `/regional/` — 都道府県別推移
- `/employment-economy/` — 雇用・賃金
- `/business-industry/` — 企業・産業
- `/listed-companies/` — 上場企業
- `/economy-prices/` — 経済・物価
- `/energy/` — エネルギー
- `/about-data/` — データ出典・定義
- `/privacy/` — プライバシー・広告・Cookie
- `/analytics/` — サイト統計

## 5. データ配置
- `data/raw/` — 原典・取得ファイル。原則Git管理外。
- `data/public_it.db` — 公共調達の運用SQLite。
- `src/data/` — Astroビルド時に使う生成データ。
- `public/data/` — ブラウザ・Functionsから参照する公開JSON。
- `dist/` — Astro build成果物。Cloudflareへ配信。

## 6. 画面設計原則
- 日本語を基本言語とする。
- 数字だけでなく「その数字の意味・出典・限界」を近接表示する。
- 億円・兆円・万円等、日本の利用者が読みやすい単位で表示する。
- 負の会計値は赤、それ以外は黒を基本とする。
- モバイルでは横スクロール依存を減らし、必要な表のみ明示的にスクロールさせる。
- データが無い場合は「0」と「未取得」を混同しない。

## 7. SEO基本設計
- canonicalを各index対象ページに付与する。
- `robots.txt` でクロール許可し、sitemapを公開する。
- sitemapは静的ページに加え、index対象の動的企業詳細URLも生成する。
- 上場企業は財務あり企業だけをsitemapへ含める。
- 企業詳細はCorporation / WebPage / BreadcrumbList等の構造化データを出力する。

## 8. キャッシュ・配信ヘッダー
`public/_headers` で共通セキュリティヘッダーを付与する。
公開JSONは `Cache-Control: public, max-age=3600, stale-while-revalidate=86400` とし、更新頻度と配信効率を両立する。
`/vendor/*` は長期immutableキャッシュとする。
動的企業詳細も同様に1時間キャッシュ＋stale-while-revalidateを返す。

## 9. 外部依存の考え方
- データ取得は公式ソースを優先する。
- 外部JSは必要最小限にし、地図等は可能な範囲でサイト内配信する。
- 有料APIがないと成立しない機能は原則採用しない。
- TDnet API等、有料条件があるデータは必須機能にしない。

## 10. 障害分離
- 収集失敗時は公開更新を止める。
- 公共調達DBは日次処理前にバックアップする。
- 静的ページと動的Functionsを分離し、Functions障害時も静的領域全体が巻き込まれない構成とする。
- 主要データはpublic向け圧縮JSONとRaw/normalized原本を分離する。

## 11. 変更管理
- GitHub `main` をコードの正本とする。
- UbuntuをRawデータ・運用実行環境の正本とする。
- 生成JSONだけの変更と、ソースコード変更を同一コミットに不用意に混在させない。
- 仕様変更時は本ディレクトリの該当設計書を更新する。
