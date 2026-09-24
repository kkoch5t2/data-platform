# DATLUME

日本のさまざまなデータをテーマ別に可視化するデータサイトです。現在は公共調達と、不動産・防災・暮らしの2領域を公開対象にしています。

## 構成
- 収集: Python標準ライブラリでJETRO政府公共調達DBの公開情報を取得
- 分野分類: GPT/APIなし。案件名からルールベースで主分類・関連分類を付与
- IT深掘り: IT案件にはクラウド、セキュリティ、生成AI等の技術タグも付与
- 保存: ローカルSQLite + 生成JSON（公開リポジトリには収集済み公共調達データを含めない）
- 表示: Astro + EChartsの静的サイト
- 定期更新: GitHub Actionsで毎日06:15 JST
- 固定費: 無料枠中心。外部の有料APIは前提にしない

## 公開データ基盤
- 公共調達 (`/procurement/`): JETRO / GEPSの公開調達情報を収集・分類・可視化
- 不動産 × 防災 × 暮らし: 国土交通省「地価公示」2026年全国25,565地点を地図化
- 地域統計: 人口・高齢化率・犯罪率・交通事故を地図上で切り替え表示
- 施設: 病院・学校・駅を必要時だけ遅延読込
- 飲食店: OpenFreeMap/OpenMapTiles に含まれる OpenStreetMap POI を利用し、Overpass APIへの都度問い合わせはしない
- 防災レイヤー: 国土地理院「重ねるハザードマップ」の洪水・津波・土砂災害オープンタイルを重畳
- 地図: MapLibre GL JS 6.11.1をサイト内配信 + OpenFreeMap。Google Maps等の従量課金APIは使用しない
- 新しいデータソースは `collector/source_catalog.json` に登録し、共通ランナーから実行する

## 分野
IT・デジタル、建設・土木、医療・福祉、研究・調査・コンサル、教育・研修、
交通・物流、施設管理・清掃、広報・広告・制作、エネルギー・環境、食品・給食、
一般物品・備品、その他。

## ローカル実行
npm run collect
npm run dev
npm run build

## 全分野の過去データ取得
JETROの現行検索で一括取得できる2021年4月1日以降を対象に、国・独立行政法人の全公示種別と地方政府系データを回収します。

python3 collector/backfill_available.py

落札企業・金額・契約方式は詳細ページの取得が必要なので、通常更新時に段階的に補完します。

公共調達の生成ページは `/procurement/markets/`, `/procurement/companies/`, `/procurement/organizations/`, `/procurement/technologies/`, `/procurement/years/` 以下です。

トップ `/` は複数データ領域への入口として使い、各領域は独立したURL配下に置きます。データソースには `country` と `domain` を持たせ、将来の国・分野追加に備えます。

## データ上の注意
収録元はJETRO政府公共調達データベースです。国・独立行政法人に加え、JETRO地方政府検索に掲載される都道府県・政令指定都市・地方独立行政法人なども対象です。全国すべての市区町村を網羅するデータではありません。
現行検索から一括取得できる最古は2021年4月1日です。2020年以前の個別ページが残っていても完全列挙できないため、時系列集計には混在させません。分野分類は案件名ベースのため境界案件や誤分類がありえます。
確認済み落札総額は、詳細取得済みの案件だけを合計した値で、市場総額そのものではありません。

## リリース
- 本番前確認: `npm run release:check`
- 静的ホスティングのビルドコマンド: `npm run build`
- 公開ディレクトリ: `dist`
- Cloudflare Pages等では `public/_headers` のキャッシュ・セキュリティ設定を利用可能
- `public/robots.txt` でクロールを許可
- `.github/workflows/ci.yml` でpush/PR時に監査とビルドを確認
- `.github/workflows/living-data.yml` で地価・暮らし系公開データを月次更新
- `.github/workflows/deploy-pages.yml` からCloudflare Pagesへ手動デプロイ可能
- デプロイにはGitHub Secrets `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` と、Repository Variable `CLOUDFLARE_PAGES_PROJECT` を設定する

本番ドメインが決まったら canonical URL / sitemap / OGP URL を設定する。

## Repository data policy

このリポジトリはソースコードをMIT Licenseで公開します。収集済みの公共調達データ（年別JSON、集計JSON、ダッシュボードJSON）はリポジトリには含めません。各データの権利・利用条件は各提供元に帰属し、MIT Licenseの対象ではありません。

ローカルで収集処理を実行すると、Git管理外の生成データとして作成されます。公開データを利用する場合は、各提供元の最新の利用条件を確認してください。

Third-party dependencies and vendored assets retain their own licenses. The vendored MapLibre GL JS files include their BSD-3-Clause license under `public/vendor/maplibre-6.11.1/LICENSE.txt`.
