# DATLUME QA・テスト設計書

最終更新: 2026-10-01

## 1. 品質方針
DATLUMEは「画面が開く」だけでなく、数値・出典・リンク・操作・モバイル表示・データ整合性まで確認する。
テストはローカルだけで完了扱いにせず、重要変更では本番URLも再確認する。

## 2. データ監査
`npm run audit:data` で、公開データ間の整合性、件数、必須項目、異常値等を全件検査する。`npm run audit:wikipedia-topics` では話題ページのTOP100件数、順位・PV降順、重複、特殊ページ混入、直近鮮度、急上昇・週間集計の整合を検査する。
構成は `audit-data-integrity.py`、生活・履歴系を深掘りする `audit-living-history.py`、上場企業正規化を検査する `audit-listed-normalized.py`、正規化値から公開64 shard/indexへの変換一致を検査する `audit-listed-public.py`。大量件数でも全件走査を前提とし、失敗時はリリースを止める。
市区町村座標、犯罪・事故、病院/学校/駅POI、履歴年次グリッド、派生式、source-nativeな欠損許容範囲まで監査対象とする。

## 3. EDINET/XBRL監査
`npm run validate:listed-financials` で、企業文書種別、連結/個別context、unit、従業員数・株式数presentation、セグメント、主要株主、検証済み補正、持続しない極端な桁変動を検査する。
`npm run audit:listed-cross-filing` は当年値と翌年有報の前期比較値を、同一concept・連結区分・period type・unitで突合する。10倍以上の新しい不一致は失敗とし、確認済みの過年度組替え・訂正・比較表側の原典異常だけを値付きallowlistで管理する。
単純な前年比10倍は、赤字転落・増資・事業売却等でも起こり得るため、それだけで誤りとは判定しない。前後年が近いのに中間年だけ10倍以上跳ねる「往復型」は `audit-listed-normalized.py` で全件検出し、原典確認済みの値付き固定リストだけを許可する。新規往復型はFAIL。同一年度の翌年有報比較でも10倍以上食い違う場合は `audit-listed-cross-filing.py` でFAILする。さらに最新年度は翌年有報で再確認できないため、安定指標の前年比10倍以上を原典確認済みペアとして固定し、新規の10倍以上変動はFAILする。
`npm run audit:listed-source` は全正規化レコードを変換CSVの完全一致concept/contextと再照合し、現在の選択ルールで選ばれる原典factと保存済みsourceが一致することも確認する。重いため週次監査で実行する。
`npm run audit:listed-xbrl` ではXBRLサンプルとの対応を別系統で検査する。
平均年間給与は通常監査に加え `npm run validate:listed-salary` で外れ値候補をiXBRL表示まで再確認する。原典表示が一致していても10倍級の給与変動が残れば未解決として停止する。訂正値を一意に確定できる原典異常だけ検証済み補正し、一意に確定できない原典異常は推測値を作らずその年度を欠損扱いにする。主要株主は `npm run validate:listed-shareholders` で変換CSVの欠落候補を検出し、必要時だけiXBRL presentationから再検証する。

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
