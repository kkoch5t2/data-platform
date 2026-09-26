# DATLUME セキュリティ設計書

最終更新: 2026-09-27

## 1. 基本方針
DATLUMEは公開データ中心のサイトだが、APIキー・Cloudflare認証情報・運用ファイルは公開情報ではない。
シークレットをGit、生成HTML、public配下、ログへ出さないことを最優先とする。

## 2. EDINET APIキー
コードは `EDINET_API_KEY` 環境変数または `~/.config/datlume/edinet_api_key` から取得する。
ファイル利用時は0600またはそれより厳しい権限を必須とし、group/otherに権限がある場合は処理を停止する。
APIキーそのものを設計書・ログ・commitへ記録しない。

## 3. Cloudflare認証
`deploy-datlume.sh` は以下のローカルファイルから認証情報を読む。
- `~/.datlume-cloudflare-token`
- `~/.datlume-cloudflare-account-id`
これらはGit管理対象外とし、存在しない場合はデプロイを失敗させる。

## 4. 公開可能な識別子
AdSense publisher IDやads.txtの販売者行など、Googleの仕様上公開される識別子はpublic配下に置いてよい。
秘密鍵・API token・アカウント認証情報とは区別する。

## 5. HTTPセキュリティヘッダー
`public/_headers` とPages Functionsで以下を付与する。
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Frame-Options: SAMEORIGIN`
- `Permissions-Policy: geolocation=(), camera=(), microphone=()`

## 6. 動的HTML
Pages Functions内ではHTMLへ埋め込む文字列をescapeする。
JSON-LDやscript JSONでは `<` をUnicode escapeし、script閉じタグ等の混入リスクを下げる。
外部URLは許可プロトコルをHTTP/HTTPSに限定する。

## 7. Git運用
- commit前に意図しない生成データ・秘密情報を確認する。
- 日次scheduled deployは未許可のソース差分がある場合停止する。
- 生成JSONとコード変更を可能な限り分離する。
- APIキーの値をgrep結果やコミットメッセージへ出さない。

## 8. ログ・プライバシー
Cloudflare等の配信基盤ではIPアドレス、User-Agent、アクセス日時、リクエスト先、エラー情報が処理される場合がある。
サイト側で不要な個人追跡を追加しない。
Cloudflare Web Analyticsは現行設定ではCookieを利用しないアクセス解析として扱う。
広告導入後はGoogle/CMPの仕様変更に応じてprivacy文面を更新する。

## 9. 外部依存
外部CDNや第三者スクリプトは必要性を確認して導入する。
地図ライブラリ等、固定化できるものは可能な範囲でサイト内配信する。
新規外部サービスを導入する際は、費用、利用規約、データ送信内容、障害時影響を確認する。

## 10. Bot・クローラー対策
DATLUMEの独自ドメイン `datlume.com` では、2026-09-27時点で以下を有効化している。
- Bot Fight Mode: ON
- AI bots protection: `block`
- crawler protection: `enabled`
- JavaScript detection: ON
- `cf_robots_variant`: `policy_only`

検索エンジン等の正規Verified BotはSEOのため一律遮断しない。2026-09-27時点では、中国（CN）・ロシア（RU）・香港（HK）からのアクセスについて、Cloudflare Verified Botを除外したうえでBlockするWAF Custom Ruleを有効化している。国別Blockは、国だけで機械的に拡大せず、国別・bot別アクセス実態を確認してから追加する。特に米国発トラフィックには検索クローラーが含まれ得るため、米国全体のBlockは禁止する。

## 11. 障害・攻撃時の考え方
- 異常なFunctions負荷が続く場合はCloudflare分析で経路を確認する。
- 動的ページはRaw DBへ直接接続しないため、Web経由で運用DBを変更できない設計を維持する。
- 404入力は早期に形式検証し、不正なコード/IDでshard探索を行わない。
- 配信上限やCPU上限へ近づく場合、Bot/WAF設定を先に検証し、その後に企業詳細の静的化またはキャッシュ強化を検討する。

## 12. レビュー項目
セキュリティに関わる変更では最低限以下を確認する。
- 新しいsecretの保存場所
- public/distへの秘密値混入有無
- HTML escaping
- 外部URL検証
- 新しいCookie/計測タグのprivacy記載
- Cloudflare権限が必要最小限か
