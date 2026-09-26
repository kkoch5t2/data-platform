# DATLUME 詳細設計書

最終更新: 2026-09-27

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
