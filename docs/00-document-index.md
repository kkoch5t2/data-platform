# DATLUME 設計ドキュメント一覧

最終更新: 2026-10-01

このディレクトリは、DATLUME の要件・設計・データ・運用・品質・収益化・セキュリティを、実装と一緒に管理するための正式ドキュメント置き場です。
コード変更時は、仕様に影響する場合は該当文書も同じコミットで更新してください。

## 文書
- `01-requirements.md` — 要件定義。目的、対象領域、機能要件、非機能要件、制約。
- `02-basic-design.md` — 基本設計。全体アーキテクチャ、画面・配信方式、コンポーネント境界。
- `03-detailed-design.md` — 詳細設計。主要モジュール、処理フロー、URL・shard・Function設計。
- `04-data-design.md` — データ設計。ソース、Raw/Normalized/Public、会計・欠損・品質ルール。
- `05-operations.md` — 運用設計。日次/月次/週次、バックアップ、デプロイ、障害時対応。
- `06-test-quality.md` — QA・テスト設計。監査、E2E、PC/モバイル、本番確認。
- `07-monetization-adsense.md` — Google AdSense 導入・審査・広告配信方針。
- `08-security.md` — シークレット、HTTPヘッダー、外部API、Git運用のセキュリティ設計。
- `09-system-inventory.md` — 画面・データソース・collector・運用スクリプトの横断索引。
- `listed-companies-prd-notes.md` — 上場企業領域のPRD実装判断と会計ルール。

## 正式な参照順
1. 実際の動作はソースコード・生成データが最終的な事実。
2. 仕様意図はこの `docs/` を参照。
3. データソースの実登録状況は `collector/source_catalog.json` を参照。
4. 実行可能コマンドは `package.json` を参照。
5. 公開経路は `public/_routes.json`、配信ヘッダーは `public/_headers` を参照。

## 重要原則
- 公開データを優先し、追加有料APIを前提にしない。
- 欠損値を推測で埋めない。
- データ収集と公開を分離し、Webには公開用に圧縮したデータだけを置く。
- 本番は build / audit / E2E を通してから反映する。
- PC と幅390px相当のモバイルを両方検証する。
