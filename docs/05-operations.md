# DATLUME 運用設計書

最終更新: 2026-09-27

## 1. 運用環境
- Ubuntu 正本: `$HOME/Sites/public-market-data`
- Node.js: 22系
- デプロイ先: Cloudflare Pages project `datlume`
- 本番: `https://datlume.com/`
- コード正本: GitHub `main`
- Raw/運用データ正本: Ubuntuローカル

## 2. 日次更新
`scripts/daily-refresh.sh --scheduled` を06:15 JST以降に毎時起動し、その日の成功後はスキップする設計。
ホスト側cronはリポジトリ外設定のため、変更時はサーバ上のcrontabも確認する。

現行の想定cron:
```cron
15 6-23 * * * $HOME/Sites/public-market-data/scripts/daily-refresh.sh --scheduled >/dev/null 2>&1
@reboot /bin/bash -lc 'sleep 120; $HOME/Sites/public-market-data/scripts/daily-refresh.sh --scheduled' >/dev/null 2>&1
30 3 * * 0 $HOME/Sites/public-market-data/scripts/weekly-audit.sh >/dev/null 2>&1
```

## 3. 日次処理フロー
1. flockで多重起動防止。
2. scheduled時は未許可のGit差分があれば停止。
3. 空き容量10GiB未満なら停止。
4. 公共調達DBをバックアップ。
5. 前回成功日から当日まで公共調達をcatch-up。
6. 公共調達health check。
7. 月初回のみJPX/EDINET企業マスタ更新。
8. EDINET文書取得、download、incremental normalize。
9. 平均年間給与外れ値を原典検証。
10. 上場企業正規化データの全件整合・異常値監査。前後年が近いのに中間年だけ10倍以上動く往復型に加え、翌年有報がまだない最新年度の安定指標も前年比10倍以上をレビュー対象とする。原典確認済みの固定値だけ許可し、新規候補は停止する。
11. 同一年度を翌年有報の前期欄と照合する10倍cross-filing監査。未確認の10倍以上不一致は停止。
12. 上場企業public data再生成。
13. 月初回のみ各統計領域更新。
14. Cloudflare Web Analyticsスナップショット更新。
15. 公開予定の全領域データ監査を実行。失敗時はbuild/deploy前に停止。
16. build、Cloudflare deploy。
17. 成功履歴とlast-success-date更新。

## 4. 週次監査
`scripts/weekly-audit.sh` は週1回、以下を実行する。
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

## 6. 障害時対応
- 公共調達収集失敗: バックアップDBへ復元し、その日のデプロイを中止。
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
- `history.jsonl`
- `daily-refresh.lock`
- `weekly-audit.lock`
- `release.lock`

## 8. 手動運用
- 全体確認: `npm run release:check`
- build: `npm run build`
- 本番deploy: `bash deploy-datlume.sh`
- 上場企業日次相当: `npm run refresh:listed-daily`
- データ監査: `npm run audit:data`
- HTML監査: `npm run audit:html`
- E2E: `npm run e2e:deep`
