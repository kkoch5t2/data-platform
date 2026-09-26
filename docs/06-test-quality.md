# DATLUME QA・テスト設計書

最終更新: 2026-09-27

## 1. 品質方針
DATLUMEは「画面が開く」だけでなく、数値・出典・リンク・操作・モバイル表示・データ整合性まで確認する。
テストはローカルだけで完了扱いにせず、重要変更では本番URLも再確認する。

## 2. データ監査
`npm run audit:data` / `scripts/audit-data-integrity.py` で、公開データ間の整合性、件数、必須項目、異常値等を検査する。
大量件数でも全件走査を前提とし、失敗時はリリースを止める。

## 3. EDINET/XBRL監査
`npm run audit:listed-xbrl` で、正規化値と原典XBRL/CSVの対応を検査する。
平均年間給与は通常監査に加え `npm run validate:listed-salary` で外れ値候補をiXBRL表示まで再確認する。

## 4. HTML監査
`npm run audit:html` / `scripts/audit-generated-html.py` で全静的HTMLを走査する。
主なチェック:
- title / viewport / favicon / canonical / H1
- headerロゴ
- `undefined` / `NaN` の可視露出
- 内部リンク切れ
- sitemapと上場企業indexabilityの一致
- AdSense所有権meta、`ads.txt`、privacyページの存在

## 5. E2E
Playwrightベースの `scripts/e2e-deep.cjs` を使用する。
PCと幅390px相当のモバイルを両方検証する。
主な観点:
- HTTP 200
- ブランド表示
- JS例外
- 自サイトHTTPエラー
- 外部HTTPエラー
- 横はみ出し
- 読み込み停止
- canvas/chart生成
- table表示

## 6. 代表ルート
週次本番E2Eでは少なくとも以下を含める。
- `/`
- `/listed-companies/`
- `/listed-companies/7203/`
- `/listed-companies/compare/`
- `/procurement/`
- `/procurement/companies/co_f96b284bc087/`
変更内容に応じて `/privacy/` や対象領域を追加する。

## 7. Visual QA
自動E2E後、UI変更を伴う場合はスクリーンショットをPC/モバイルで目視する。
確認項目:
- 余白、カード高さ、文字切れ
- グラフ凡例・軸・単位
- クリック対象の大きさ
- 色の意味の一貫性
- モバイル縦長化や不要な空白
- 重要注記が画面外へ追いやられていないか

## 8. 数値QA
- 0と欠損を区別する。
- 表示単位変換前の内部値を確認する。
- 急激な前年比変化は原典確認対象とする。
- ランキング上位の極端値はサンプル原典照合する。
- 金融業等、意味の異なる指標を同一ランキングへ混ぜない。

## 9. リリース判定
以下のどれかが失敗した場合、原則リリースしない。
- データ監査
- build
- HTML監査
- 対象機能のE2E
- 必要な原典照合
本番反映後に同じ主要ルートを再確認し、ローカルのみ成功を完了条件としない。
