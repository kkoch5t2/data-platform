# DATLUME 運用設計書

最終更新: 2026-10-05

## 1. 運用環境
- Ubuntu 正本: `$HOME/Sites/public-market-data`
- Node.js: 22系
- デプロイ先: Cloudflare Pages project `datlume`
- 本番: `https://datlume.com/`
- コード正本: GitHub `main`
- Raw/運用データ正本: Ubuntuローカル

## 2. 日次更新
`scripts/daily-refresh.sh --scheduled` を06:15 JST以降に毎時起動し、その日の成功後はスキップする設計。話題のトピックはWikimediaの日次集計公開時刻に合わせ、通常更新から分離して14:15〜23:15 JSTに毎時 `scripts/refresh-wikipedia-topics.sh --scheduled` を実行する。
ホスト側cronはリポジトリ外設定のため、変更時はサーバ上のcrontabも確認する。

現行の想定cron:
```cron
15 6-13,15-23 * * * $HOME/Sites/public-market-data/scripts/daily-refresh.sh --scheduled >/dev/null 2>&1
15 14-23 * * * $HOME/Sites/public-market-data/scripts/refresh-wikipedia-topics.sh --scheduled >/dev/null 2>&1
@reboot /bin/bash -lc 'sleep 120; $HOME/Sites/public-market-data/scripts/daily-refresh.sh --scheduled' >/dev/null 2>&1
30 3 * * 0 $HOME/Sites/public-market-data/scripts/weekly-audit.sh >/dev/null 2>&1
```

## 3. 日次処理フロー
1. `scheduled-refresh.py` がジョブごとのflockを取得し、Git正本を変更しない専用のdetached worktreeで収集する。日次・週次はDB/正規化データを共有するため `update.lock` で直列化する。トピックはこのロックを取得せず独立して収集できる。公開時だけ共通の `release.lock` を取得する。
2. scheduled時は未許可のGit差分があれば停止。
3. 空き容量10GiB未満なら停止。
4. 収集前にSQLite backup APIでDBを検証・保存し、EDINET文書索引と正規化データをまとめてスナップショットする。月次/週次マーカーは作業場所の一時領域へコピーし、本番検証成功まで共有状態へ反映しない。WAL内のcommitも含め、壊れたDBで既存バックアップを上書きしない。
5. 前回成功日から当日まで公共調達をcatch-up。JETROのJSON復元では既存IDは機関名の補完だけを行い、新規IDだけを分類・挿入する。既存案件の分類や財務・落札値をJSONで再上書きしない。
6. 公共調達health check。
7. 月初回のみJPX/EDINET企業マスタ更新。
8. EDINET文書取得、download、incremental normalize。
9. 平均年間給与外れ値を原典検証。
10. 上場企業正規化データの全件整合・異常値監査。前後年が近いのに中間年だけ10倍以上動く往復型に加え、翌年有報がまだない最新年度の安定指標も前年比10倍以上をレビュー対象とする。原典確認済みの固定値だけ許可し、新規候補は停止する。
11. 同一年度を翌年有報の前期欄と照合する10倍cross-filing監査。未確認の10倍以上不一致は停止。
12. 上場企業public data再生成。
13. 月初回のみ各統計領域更新。住宅・土地2023、人口・世帯、小売価格都市、社人研の市区町村将来人口は独立した月次マーカーで実行し、鮮度を検査する。
14. Cloudflare Web Analyticsスナップショット更新。
15. scheduledの日次更新ではWikipedia話題トピックを更新せず、14:15 JSTの専用ジョブへ分離する。
16. 公開予定の全領域データ監査を実行。失敗時はbuild/deploy前に停止。

### 3.1 Wikipedia話題トピック専用更新
`scripts/refresh-wikipedia-topics.sh --scheduled` を14:15〜23:15 JSTに毎時再試行する。当日成功すると `last-wikipedia-success-date` に記録してスキップし、失敗は `wikipedia-failures.log` に記録する。Wikimedia Pageviewsの取得後、MediaWiki/Wikidataでカテゴリ分類し、Google News RSSで急上昇の背景候補を補完する。YouTube APIキーが設定済みなら、急上昇上位10件を直近7日の日本向け・埋め込み可能動画と照合する。独立したworktreeで取得・専用監査する。朝の日次収集が実行中でも公開ロックが空けばbuild・commit/push・deployできる。トピックの公開が先に完了した場合、日次公開は新しいトピックJSONを取り込む。ニュースまたはYouTube取得だけの失敗ではWikipediaランキング更新を止めない。
17. 公開ロック内で最新mainへ生成差分を反映する。取得中に別ジョブが更新した `sources.json` はソース単位でマージする。同一ファイル・同一ソースの競合、収集中のコード変更は公開を止め、次回再取得する。トピック公開は最新の日次公開済みのGit管理外データを再読込し、調達を古い状態へ戻さない。
18. 全領域監査（日次）または専用監査（トピック）、build、HTML監査、Wrangler Pagesローカル環境で主要ルートと動的詳細のPC/モバイルE2Eを実行する。
19. 生成差分だけGitへcommit/pushし、正本mainをfast-forwardする。日次のGit管理外データもここで同期する。Cloudflare deploy後、公開manifest/JSON/XMLの一致と主要ページのPC/モバイル本番E2Eを確認する。
20. 全確認成功後だけ月次マーカー・成功履歴・last-success-dateを更新する。取得成功やHTTP 200のみで成功扱いにしない。

### 3.2 YouTube照合の秘密設定
YouTube照合は任意機能。APIキーはGit管理せず、`YOUTUBE_API_KEY` 環境変数または `~/.config/datlume/youtube_api_key` から読む。キー未設定時はYouTube部分だけ安全にスキップする。

推奨配置:
```bash
mkdir -p ~/.config/datlume && chmod 700 ~/.config/datlume
printf '%s\n' 'YOUR_API_KEY' > ~/.config/datlume/youtube_api_key
chmod 600 ~/.config/datlume/youtube_api_key
```

### 3.3 Search Console監視の秘密設定
Google Search Console監視は公式Search Console APIを使う。OAuthクライアントJSONと取得済みtokenはGit管理せず、`~/.config/datlume/gsc/` に権限600で保存する。

配置:
```bash
mkdir -p ~/.config/datlume/gsc && chmod 700 ~/.config/datlume/gsc
chmod 600 ~/.config/datlume/gsc/credentials.json ~/.config/datlume/gsc/token.json
```

通常確認:
```bash
python3 scripts/check-gsc-sitemap.py
```

GUIブラウザが使える端末での初回認証は `--authorize`。ヘッドレス端末では `--headless-start` で認証URLを発行し、Google同意後のlocalhost callback URLを `--complete-stdin` へ標準入力してtokenを保存する。

## 4. 週次監査
`scripts/weekly-audit.sh` は週1回、日次とは別の隔離worktreeで以下を実行する。DBと正規化データを使う間は日次と共通のupdate.lockを保持し、失敗時は復元する。公開用ファイルの生成がGit正本へ未コミット変更を残すことはない。週次監査自体は本番へdeployしない。
- 平均年間給与外れ値検証
- 主要株主のpresentation補完検証
- 上場企業正規化データ監査
- 上場企業public data再生成
- 全体データ監査
- 当年値と翌年有報の同一unit・前期比較値を突合するcross-filing監査
- 上場企業の全正規化値を変換CSVの完全一致concept/contextへ再照合するsource監査
- EDINET/XBRLサンプル監査
- full build
- HTML監査
- 本番E2E

ログは `data/automation/weekly-audit-logs/` に保存し、90日超を削除する。

## 5. デプロイ
`deploy-datlume.sh` は以下を満たさない場合デプロイを拒否する。
- 公共調達shardとレコード数が最低条件を満たす。
- 公共調達企業詳細shardが256個ある。
- 上場企業詳細shardが64個ある。
- 上場企業数3,000社以上、財務年度30,000件以上。
- Pages Functionsがbuildできる。
- `dist` ファイル数20,000以下。
- 単一ファイル25MiB以下。

Cloudflare認証情報はホームディレクトリ配下の専用ファイルから読み、リポジトリへ置かない。
`deploy-datlume.sh` はupload前に `dist/data/release-manifest.json` を生成する。主要公開JSON、統計JSON・直近dashboard shard、sitemapとshardの両端サンプルのSHA-256・bytesを保持し、deploy後に本番と照合する。manifest自体のreleaseId一致も必須。キャッシュ伝播遅延は最大6回再試行し、最後まで不一致ならdeployコマンドを失敗扱いにする。結果は `last-production-verification.json` へ保存する。manifestはdist成果物だけに置き、秘密やローカルパスを含めない。

## 6. 障害時対応
- 調達、上場企業、統計、トピック、build、ローカルE2E失敗: Git正本と公開済みデータを変更しない。未pushの日次/週次はDB・文書索引・正規化データを復元し、新規の正規化ファイルも除去する。取得Rawと失敗sourcesを証跡として残す。成功日と月次マーカーを更新しない。
- INT/TERM: collectorの子プロセスグループを停止・終了確認してから復元する。SIGKILL/停電: `transactions/<job>/manifest.json` を次回起動時に読み、同じ起動IDの残存collectorを止めてから復元する。日次/週次は相手ジョブの未完了transactionも復旧してから開始する。
- push成功後のdeploy/本番確認失敗: 公開Git履歴を巻き戻さず、DB・正規化・正本をcommit済み状態へ保つ。成功日と月次マーカーは進めず、次回起動で再取得・検査・deployする。push応答が失われた場合もorigin/mainへのcommit包含を確認して判断する。確認不能なら復元せずtransactionを保存する。
- 横浜市の結果一覧は1回60秒、最大5回の通信再試行と失敗ログを持つ。
- health check失敗: デプロイを中止。
- EDINET給与外れ値未解決: 上場企業更新を失敗させる。原典自体が異常で訂正値を確定できない場合は推測補正せず、その年度の値を欠損扱いにする。
- 上場企業のunit/context/連結選択/異常値監査に未解決がある: public data生成前に停止する。
- 全領域データ監査に欠損・式不整合・重複・範囲異常がある: build/deployを停止する。
- build/audit失敗: 本番反映しない。
- Cloudflare deploy失敗: last-success-dateを書かず、次回scheduledで再試行可能にする。

## 7. ログ・状態ファイル
主な状態は `data/automation/` に保持する。
- `logs/YYYY-MM-DD.log`: 日次処理の全標準出力・監査FAIL/WARN。
- `logs/failures.log`: 日次処理が停止した時刻、step、終了コード、失敗コマンド、対応する日次ログ。
- `weekly-audit-logs/YYYY-MM-DD.log`: 週次監査の全出力。
- `weekly-audit-logs/failures.log`: 週次監査の停止理由。
- `last-success-date`
- `last-listed-master-refresh`
- `last-monthly-refresh`
- last-monthly-secondary-refresh
- last-wikipedia-success-date / wikipedia-failures.log
- `history.jsonl`
- `daily-refresh.lock`
- `weekly-audit.lock`
- `release.lock`
- `update.lock`: 日次/週次のDB・正規化データ排他
- `workspaces/daily`, `workspaces/topics`, `workspaces/weekly`: ジョブ別の隔離Git作業場所
- `transactions/<job>/manifest.json`: 中断復旧用状態、DB/正規化スナップショット
- `last-production-verification.json`: 最後の公開データ照合結果
- `logs/<job>-failure-sources-*.json`: 失敗時の取得状況証跡
- `procurement-refresh-snapshot/`: 2026-10-04までの旧復元用状態（現行更新では使用しない）

## 8. 手動運用
- 全体確認: `npm run release:check`
- build: `npm run build`
- 本番deploy: `bash deploy-datlume.sh`
- 上場企業日次相当: `npm run refresh:listed-daily`
- Wikipedia話題トピック専用更新: `bash scripts/refresh-wikipedia-topics.sh --scheduled`
- Wikipedia話題トピック収集: `npm run collect:wikipedia-topics`
- Wikipedia話題トピック監査: `npm run audit:wikipedia-topics`
- データ監査: `npm run audit:data`
- HTML監査: `npm run audit:html`
- E2E: `npm run e2e:deep`

## 9. 移行・運用確認
cronの呼び出しパス・時刻は従来どおり。日次/トピック/週次のshellは新しいオーケストレータを起動する薄い入口になる。`collect-daily.sh` と `weekly-audit-worker.sh` は専用作業場所からのみ実行する。
通常手動更新も隔離・Git反映・検証を通す。`--scheduled` は認可ホスト・当日成功スキップ・06:15以降の日次起動を追加する。
主要本番ページはトップ、トピック、調達、上場企業、上場企業7203、未上場企業。生成データのみ変わった別ジョブのcommitを公開直前に取り込めるが、収集中のソース変更・同じファイルの競合では公開を止める。
復旧snapshotは処理成功/復旧完了時に削除する。直近の隔離作業場所は次回起動時に再作成する。ジョブのRawは共有して取得済み証跡を保持する。ローカルGitに既存のユーザー変更があれば破棄せず停止する。

住宅・土地、人口・世帯、小売価格の月次生成JSONもscheduled Git許可対象に含め、これらが更新された場合に公開前チェックで止まらないことを検査する。


## しょくばらぼ職場情報（2026-10-05追加）
日次の上場/未上場公開データ生成前にcollect:shokubaとhealth --source shokubaを実行する。公式ZIPは過去原本も保持。workplace.sqliteを隔離更新の復旧対象へ追加し、収集/監査失敗では公開を止める。

社人研の将来人口は `last-ipss-population-refresh` マーカーで月初回に原典4表を再取得し、スキーマ・1,884地域・年齢3区分・2020年人口の整合監査後に公開する。


### 小売物価の履歴バックフィルと月次更新

一度だけ npm run backfill:retail-prices-city を実行して原表を保存・組み立てる。--years 2000-2000 --download-only のような部分取得も可能。各年のe-Stat一覧を再照合し、公開ファイルの分割が変わった月だけパース済みスナップショットを再取得する。通常の npm run collect:retail-prices-city は2000年以降の既存履歴を保持して最新24か月を再取得する。最新品目の単位が変わった場合は失敗させ、履歴比較の見直しを要求する。更新後 npm run audit:retail-prices-city を実行する。

## Gビズインフォ補助金・特許（月次）
日次処理では独立した `last-gbiz-activity-refresh` 月次マーカーを使い、月初回に `collect:gbiz-subsidy` と `collect:gbiz-patent` で公式ZIPを取得する。上場・未上場のpublic生成はZIPを読み法人番号で照合し、検証済みの記録だけを企業詳細shardに入れる。マーカーは本番確認成功後のみ確定する。ZIPはGitに含めずRawとしてホストに保持する。

## 宿泊旅行統計の月次更新
`last-lodging-statistics-refresh` を独立したマーカーとし、月初回に観光庁の推移表を再取得する。ソース監査・PC/モバイルE2Eと本番確認が成功した後だけ共有マーカーを確定する。新設時に既存の月次マーカーが当月更新済みでも初回取得する。

## 気象庁の観測所データ
`npm run collect:jma-weather` で全国の観測所マスター・月別履歴・日別366日を更新する。収集器は公式のダウンロード画面のCSV取得エンドポイントを利用し、30観測所ごとに分割、間隔を空けて取得する。画面仕様が変わって列順・品質・日付に相違があれば失敗させ、推測で置き換えない。`npm run audit:jma-weather` と `python3 collector/check_health.py --source jma_weather` を実行する。日次ジョブでは独立した月次マーカー `last-jma-weather-refresh` を使う。観測所一覧に所在地のない地点は市区町村未特定として残す。


## 公共交通データ（2026-10-06追加）

`npm run collect:public-transport` → `npm run audit:public-transport` → `collector/check_health.py --source public_transport` の成功後に専用月次marker `last-public-transport-refresh` を更新する。既存の月次markerとは独立して再試行する。ソースIDは `public_transport`、健康判定は840時間・最低12,000レコード。定期更新Git許可リストへ公開JSON4本を登録し、RawはGitに含めない。local/prod E2Eに `e2e:public-transport` を追加。公開検証manifestはJSON4本を全件ハッシュ検証し、`/transport/` をページ確認対象に含める。S12・国勢調査は固定版のため、新版公開時はスキーマ・年度を確認して更新する。

## Ubuntu Wi-Fi切断の補助監視（2026-10-07）
5GHzのBEACON-LOSSと認証タイムアウトを確認し、保存済み2.4GHz接続へ復旧した。`scripts/wifi-reconnect-watchdog.py` はwlp1s0の切断が180秒以上続いた場合に限り保存済み2.4GHzプロファイルへ再接続し、再試行間隔を600秒以上にする。正常接続・接続処理中・無線無効時は介入しない。結果はsystemd journalへ記録する。

監視はリポジトリへの追加だけでは有効にならない。管理者がホスト上で `scripts/install-wifi-reconnect-watchdog.sh` を実行する必要がある。有効化後は `systemctl status wifi-reconnect-watchdog.timer` と `journalctl -u wifi-reconnect-watchdog.service` で確認する。保存済み接続のUUIDやインターフェースを変更した場合は監視設定も更新する。

### 公共交通の収集用Python環境
公共交通のExcel原典処理にはopenpyxlが必要。Ubuntu正本の `.venv` を `python3 -m venv --system-site-packages .venv` で作成し、`.venv/bin/pip install openpyxl requests beautifulsoup4 lxml pandas` で追加する。scheduled-refreshは正本の `.venv/bin/python3` が存在すると同環境を子処理に継承し、独立worktreeでも同じ依存ライブラリを使う。2026-10-07にホスト環境を作成し、公開前の収集・原典監査を確認した。


## 更新状況の横断レポート（2026-10-08追加）

`npm run report:update-status` で有効な全ソースの収集結果・頻度・収集日時（JST）・件数・元データ対象年月、日次/トピックの公開成功日、最後の本番照合記録を一覧化する。`-- --json` は監視用JSON、`-- --check` は異常時に終了コード1。外部通信やデータ変更は行わない。

対象年月はcollectorが記録した値だけを表示し、未記録は推測しない。収集日時を統計の最新年月として扱わない。収集の期限と件数下限はsource catalogに従う。本番照合記録は最新の公開成功履歴のcommitと比較し、後から追加されたコードcommitを未公開データと誤判定しない。記録に基づく確認のため、現在の本番ハッシュ照合は既存の `verify-production.py`、Google公式API確認は `check-gsc-sitemap.py` を別途実行する。

週次ジョブは公開を行わないため、日次/トピックの公開成功日とは区別して監査成功日を表示する。日次/トピックは前日以前の成功がなくなった場合、週次は成功日未記録または8日超の場合に異常として扱う。

### 日次の統計操作E2E（2026-10-08補強）
日次の公開前ローカルPages環境と公開後本番の両方で、都市別小売価格の履歴・順位・単位、社人研の市区町村将来人口比較、気象観測所の選択・期間・URL復元を専用E2Eで確認する。数値監査やcanvas存在確認だけで公開成功にせず、PC/390pxの実操作を通す。いずれか失敗した場合、従来どおり成功日を進めない。トピック専用更新ではこれらのデータを書き換えないため、既存の主要ページE2Eを継続する。

週次監査は直近の失敗時刻と、成功日ログ内のverified success時刻も比較する。8日以内の古い成功マーカーが残っていても、その後の失敗を正常扱いにしない。同じ日の再実行が成功すれば新しい成功時刻で解消判定する。
