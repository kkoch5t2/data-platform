# DATLUME

**データから、日本を見る。**

DATLUME は、日本の公共・公的データをテーマ別に収集・整理・可視化するデータサイトです。
本番: https://datlume.com/

## 公開領域
- 国・自治体の案件（公共調達）
- 不動産・暮らし
- 都道府県別推移
- 雇用・賃金
- 企業・産業
- 上場企業
- 経済・物価
- エネルギー

## 設計ドキュメント
正式な要件・設計・運用資料は `docs/` にあります。

- [文書一覧](docs/00-document-index.md)
- [要件定義](docs/01-requirements.md)
- [基本設計](docs/02-basic-design.md)
- [詳細設計](docs/03-detailed-design.md)
- [データ設計](docs/04-data-design.md)
- [運用設計](docs/05-operations.md)
- [QA・テスト設計](docs/06-test-quality.md)
- [AdSense・収益化設計](docs/07-monetization-adsense.md)
- [セキュリティ設計](docs/08-security.md)
- [システム・機能インベントリ](docs/09-system-inventory.md)
- [上場企業PRD実装メモ](docs/listed-companies-prd-notes.md)

仕様に影響する変更では、コードだけでなく該当ドキュメントも更新してください。

## アーキテクチャ概要

```text
公式データ / API / 公開Web
        ↓
Python collectors
        ↓
Raw / SQLite / normalized data (Ubuntu)
        ↓
public data generator
        ↓
Astro static build + Pages Functions
        ↓
Cloudflare Pages → datlume.com
```

基本は静的配信です。大量の個別詳細ページのうち、上場企業詳細と公共調達企業詳細だけCloudflare Pages Functionsで公開JSONからHTMLを生成します。
Webアクセス時にEDINETやJETRO等の外部APIへ問い合わせる設計ではありません。

## 技術スタック
- Astro 7
- ECharts 6
- MapLibre GL JS 6.11.1
- Python 3
- SQLite
- Playwright
- Node.js 22+
- Cloudflare Pages / Pages Functions

## データ方針
- 公式API・CSV・XLSX・JSON・公式公開Webを優先する。
- 原則として追加有料APIを必須依存にしない。
- Rawを保持し、正規化・監査後のデータだけをWeb向けに生成する。
- 欠損値や企業固有値を推測で埋めない。
- データソースの登録は `collector/source_catalog.json` で管理する。
- 出典・収録範囲・注意点は `/about-data/` で公開する。

## 主なコマンド

```bash
npm run dev
npm run build
npm run audit:data
npm run audit:html
npm run e2e:deep
npm run release:check
```

上場企業:
```bash
npm run collect:listed-master
npm run collect:listed-documents
npm run collect:listed-bulk
npm run normalize:listed-incremental
npm run validate:listed-salary
npm run build:listed-data
npm run audit:listed-xbrl
```

## 自動更新
Ubuntu上の `scripts/daily-refresh.sh` が、公共調達と上場企業を日次で更新し、月次データを同じ基盤で更新します。
収集・health check・データ生成・build・Cloudflare deployまで成功した場合だけ、その日を成功として記録します。
週次では `scripts/weekly-audit.sh` がデータ/XBRL/HTML/本番E2Eを再検証します。

## リリース
本番デプロイは `deploy-datlume.sh` を使用します。
デプロイ前に公共調達・上場企業のshard数と最低件数、Pages Functions build、Cloudflare Pagesのファイル上限を検査します。

```bash
npm run release:check
bash deploy-datlume.sh
```

## 収益化
Google AdSenseのサイト審査準備済みです。
`public/ads.txt`、トップページ所有権meta、`/privacy/`、プライバシー導線を実装しています。
広告配信方針は `docs/07-monetization-adsense.md` を参照してください。

## シークレット
EDINET APIキーやCloudflare API Tokenをリポジトリへ保存しないでください。
EDINETは `EDINET_API_KEY` または `~/.config/datlume/edinet_api_key`（0600）から読み込みます。
詳細は `docs/08-security.md` を参照してください。

## Repository data policy
このリポジトリはソースコードをMIT Licenseで公開します。
収集済みの第三者データは、各提供元の権利・利用条件に従い、MIT Licenseの対象とはみなしません。
Rawデータや運用DBの多くはGit管理外です。
公開データを再利用する場合は、各提供元の最新の利用条件を確認してください。

Third-party dependencies and vendored assets retain their own licenses.
MapLibre GL JSのvendored licenseは `public/vendor/maplibre-6.11.1/LICENSE.txt` に保持しています。

## 開発時の完了基準
重要な変更は、原則として以下の順で完了させます。

1. 実装・データ更新
2. データ監査
3. build
4. HTML監査
5. PC / 390px E2E
6. commit / push
7. Cloudflare deploy
8. 本番E2E / visual QA

ローカルで動いたことだけを完了条件にしません。
