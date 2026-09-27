# 運用Runbook

cronジョブやデプロイで何かおかしくなったときに見る場所。仕様そのものはREADME.md、コードの構造はCLAUDE.mdを参照。

## GitHub Actions が失敗したとき

対象ワークフロー: `.github/workflows/{intraday_alert,prediction,daily_scanner,weekly_performance,universe_rotator}.yml`

1. Actionsタブでどのステップで落ちたか確認。
2. `yfinance`関連のエラー(価格取得失敗)なら、Yahoo Finance側のレート制限/一時障害の可能性が高い。再実行(re-run)で直ることが多い。
3. Supabase関連のエラーが出ていても、`common/performance_tracker.py`はDB操作を try/except で囲み `data/*.json` にフォールバックする設計なので、ジョブ自体は継続するはず。ワークフローが完全に失敗している場合はフォールバック側にもバグがある可能性がある。
4. LINE/Discord通知が来ないだけでジョブ自体は成功している場合、下記「通知が来なくなったとき」を確認。
5. `universe_rotator`が落ちた場合は、J-Quants側(`JQUANTS_API_KEY`の失効・プラン変更、429の多発)を疑う。`common/market_data.py`は429を自動リトライするが、それでも落ちるならレート上限(`JQUANTS_RATE_LIMIT_PER_MIN`)を下げる。失敗した週はウォッチリストが更新されないだけで、スキャナーは前週のリストのまま動く。

## 通知が来なくなったとき

| 症状 | 確認すること |
|---|---|
| LINE通知が来ない | `LINE_CHANNEL_ACCESS_TOKEN`の有効期限切れ・失効(LINE Developersコンソールで再発行)。`LINE_USER_ID`が変わっていないか。 |
| Discord通知が来ない | `DISCORD_WEBHOOK_URL`がリポジトリのSecretsに設定されているか。未設定の場合、`common/notifier.py:13`のハードコードされた既定Webhookに送られる(下記の**要対応**参照)。 |

### 要対応: `common/notifier.py`にDiscord Webhook URLがハードコードされている

`common/notifier.py:13`に実際のWebhook URLが平文でコミットされている(README/CLAUDE.mdでも既知の課題として言及あり)。このURLを知っている第三者は誰でもそのDiscordチャンネルに投稿できる状態。

- 対応: Discord側でこのWebhookを失効・再生成し、新しいURLを`DISCORD_WEBHOOK_URL`としてGitHub Secretsと`.env`にのみ設定する。ソース中のハードコード値は削除するか、ダミー値に置き換える。
- 経緯: [[docs/decisions.md]] に理由の記録なし。バックフィル対象。

## Supabase ⇄ JSONフォールバックの切り替わりを確認する

- `SUPABASE_URL`が設定されていればDB優先、例外時は自動的に`data/signal_history.json` / `data/real_portfolio.json`にフォールバック(`common/performance_tracker.py`)。
- ダッシュボードのデータが急に古い/空に見える場合、Supabase側の接続エラーでフォールバックに切り替わっている可能性がある。Render.comのログでSupabase関連の例外が出ていないか確認する。
- ローカル開発時は`SUPABASE_URL`を意図的に未設定にすればJSONファイルのみで動く。

## ウォッチリストの入れ替えがおかしいとき

`universe_rotator.yml`(日曜 10:00 JST)は`apply=True`で`rotation`枠を自動で書き換える(`core`枠は触らない)。

- 何が入れ替わったかは、その回の通知(IN/OUT/猶予の一覧)で確認できる。現在のリストは`GET /api/watchlist`。
- 残したい銘柄が外れた場合は、`POST /api/watchlist`で`tier: core`として入れ直せば以後は自動で外れない。
- 連続基準割れの週数は各項目の`strikes`フィールドに保存されている。手でリストをいじるときはこの値も意識する。
- ローテーションをいったん止めたいときは、Actionsタブで`Universe Rotator`ワークフローを無効化する(`modules/post_analysis/universe_rotator.py`末尾の`apply=True`を`False`にすれば通知のみのドライランに戻る)。

## `main`は自動では動かない

以前は`weekly_performance.yml`が土曜に`data/signal_history.json`と`dashboard.html`を`main`へ直接pushしていたが、Supabaseを正にした時点でそのステップは削除した。今は`main`を動かすのは人のコミットだけなので、土曜日を気にせず作業してよい。リポジトリ内の`data/*.json`はその頃の古いスナップショットで、ローカルでSupabase未設定のまま動かすときのフォールバック先でしかない。

## 環境変数が正しく読まれているか確認する

ローカル: `.env`(gitignore済み)。本番(Render.com): Render側の環境変数設定。GitHub Actions: リポジトリのSecrets。3箇所は独立しているので、1箇所だけ更新して「反映されない」と思わないこと。
