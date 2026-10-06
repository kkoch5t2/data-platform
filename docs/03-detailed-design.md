# DATLUME 詳細設計書

最終更新: 2026-10-05

## 1. ディレクトリ責務
- `collector/` — 各公開ソースの収集・正規化。
- `collector/listed_companies/` — JPX/EDINET上場企業パイプライン。
- `scripts/` — build、監査、E2E、運用ジョブ。
- `src/pages/` — Astro静的ページ。
- `functions/` — Cloudflare Pages Functions。
- `public/data/` — Web公開用JSON。
- `public/vendor/` — 再配布可能な固定ライブラリ。
- `data/automation/` — ロック、状態、ログ。
- `data/backups/` — 公共調達SQLiteバックアップ。

## 2. build処理
`npm run build` は `scripts/build-locked.sh` を経由する。
Astro静的生成後、`scripts/generate-sitemap.py` がsitemapを生成し、続けてHTML監査を行う。
build中はrelease lockを使用し、日次更新と手動リリースの競合を防ぐ。

## 3. sitemap生成
`scripts/generate-sitemap.py` は `dist/**/index.html` を列挙し静的URLを生成する。
加えて以下を動的URLとして追加する。
- 上場企業: `public/data/listed-companies/index.json` の `hasFinancials=true` の証券コード。
- 公共調達企業: `src/data/companies.json` の企業ID。
URL総数が50,000件を超える場合は失敗させる。

## 4. Pages Functionsルーティング
`public/_routes.json` でFunction実行対象を限定する。
`/listed-companies/` の一覧、比較、業種ページと `/procurement/companies/` 一覧は静的配信する。
詳細だけをFunctionに流すことで、静的配信の無料・高速性を維持する。

## 5. 上場企業詳細Function
対象: `functions/listed-companies/[code].js`

### 入力
4文字の証券コード。正規表現 `^[0-9A-Z]{4}$` を満たさない場合は404。

### データ取得
証券コードから31進風のハッシュを計算し、64 shardのいずれかを選ぶ。
`/data/listed-companies/details/{00..3f}.json` を `ASSETS.fetch()` で読み、対象企業だけ取り出す。
DB・外部APIへのリアルタイム問い合わせは行わない。

### HTML生成
- title / description / canonical / OGP
- robots: 財務あり `index,follow`、財務なし `noindex,follow`
- Corporation / WebPage / BreadcrumbList JSON-LD
- KPI、最新概要、10年推移、BS、CF、働くデータ
- 検証済みの場合のみセグメント・主要株主
- 比較・同業種への内部リンク

### キャッシュ
`public, max-age=3600, stale-while-revalidate=86400` を返す。

## 6. 公共調達企業詳細Function
対象: `functions/procurement/companies/[id].js`
企業IDは `co_` + 12桁hex。`id.slice(3,5)` で256 shardの1つを選ぶ。
`/data/company-details/{00..ff}.json` から企業情報を読み、受注総額、件数、主な発注機関、落札案件表を生成する。
外部リンクはHTTP/HTTPSのみ許可し、それ以外は `#` に落とす。

## 7. 上場企業公開データ生成
対象: `collector/listed_companies/build_public_data.py`
- マスタと正規化財務を証券コードで結合。
- 企業ごとに時系列を昇順化。
- 売上成長率、利益成長率、1人当たり利益等を派生計算。
- 最新レコードをindex用に圧縮。
- 詳細を64 shardへ分割。
- ranking対象は上位100件まで生成。
- 金融業は一般企業向け売上・営業利益率ランキングから除外する。

## 8. 上場企業給与検証
対象: `collector/listed_companies/validate_salary_outliers.py`

異常候補条件:
- 100万円未満
- 2,000万円超
- 企業内中央値から3倍以上の乖離
- 前年比で3倍以上の増減

候補はEDINET原本XBRLを取得し、表示上の平均年間給与と単位を復元する。
再正規化値と表示復元値が一致しない場合は未解決として処理を失敗させる。
高年収という理由だけで補正せず、原典不整合が確認できた場合だけ置換する。

## 9. 公共調達更新
`scripts/daily-refresh.sh` からJETRO、JETRO地方政府、横浜、札幌、神戸、福岡、千葉、京都を順次更新する。
途中失敗時は公共調達DBをバックアップから戻し、本番更新を行わない。
収集後に `collector/check_health.py` でソース別の件数・鮮度を確認する。

## 10. 月次データ更新
月1回、地価・暮らし・地域・雇用・企業産業・物価・エネルギーと各履歴データを更新する。
月マーカー `data/automation/last-monthly-refresh` により同月内の重複実行を避ける。
上場企業マスタも月単位でJPX/EDINETコードリストを再取得する。

## 11. 公開データ設計上の制約
- ブラウザで不要なRaw XBRL/CSVはpublicへ置かない。
- 企業詳細はshard化し、1アクセスで全企業データを読まない。
- 欠損を0へ変換しない。
- 期間、会計基準、sourceFormat、docID等を追跡可能な形で保持する。
- データソース差がある指標は画面上で注記する。

## 12. Wikipedia話題トピック
対象: `collector/collect_wikipedia_topics.py` / `public/data/wikipedia-topics.json` / `/topics/`。
Wikimedia Analytics APIの `metrics/pageviews/top/ja.wikipedia/all-access/{year}/{month}/{day}` を直近14日分取得する。最新日が未生成の場合は最大6日前まで遡って取得可能な最新日を採用する。Rawレスポンスは `data/raw/wikipedia-topics/YYYY-MM-DD.json` に保持する。
公開JSONではメインページ・検索・名前空間ページを除外し、最新TOP100、前日比急上昇、直近7日合計、日別TOP100閲覧数を生成する。`collector/topic_enrichment.py` がMediaWiki Action APIのカテゴリ・概要とWikidataのラベル・説明・instance of・occupation・genre・sportを組み合わせ、芸能・スポーツ・事件事故・政治・ゲーム・アニメ漫画等へルールベース分類する。急上昇上位は記事名をGoogle News RSSの日本向け検索で急上昇日前後に照合し、見つかった報道を「背景候補」として最大3件保持する。ニュース取得失敗はランキング更新を失敗扱いにせず、因果関係も断定しない。日次更新失敗時は最後の正常スナップショットを保持し、DATLUME全体の定期更新は継続する。


## しょくばらぼ職場情報（2026-10-05追加）
collector/collect_shokuba.py が公式全件ZIPを保存し、634列の正確なヘッダ名で必要指標を抽出、workplace.sqliteへ原子的に正規化する。既存の上場/未上場詳細shardへworkplaceを追加。Functions共通のfunctions/_shared/workplace.jsとpublic/workplace.cssで描画し、外部APIを実行時に呼ばない。


## 公共交通データ（2026-10-06追加）

`collector/collect_public_transport.py` はS12 ZIP、国勢調査Excel、自動車輸送統計年報Excel、鉄道月報Excelを取得し、全表の検証後に `public/data/transport/{stations,commute,usage,index}.json` を書き込む。Rawは `data/raw/transport/`、内容SHA-256別の原本は `archive/` に保持する。`--offline` は保存原本から再生成する。バス・鉄道はe-Statの対象表名・ファイル種別から最新の公開表を選び、単位・ヘッダー・網羅性の変化で停止する。S12の年度・スキーマと国勢調査2020年の表は固定し、改訂時はレビューする。画面の駅選択・検索・年度・比較・地域・バス・月次/年度はクエリパラメータで復元する。
