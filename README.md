# nikkake-trade

日本株を対象にした「AI推奨シグナルの自動生成・成績トラッキング・通知」＋「実際に買った銘柄の損益管理」を行うWebダッシュボード。仕組み自体は売買を実行しない、あくまでシミュレーション/観測用のツール。

## 概要

固定ウォッチリスト銘柄をスコアリングエンジンで毎日/毎朝スキャンし、条件を満たした銘柄を「AI推奨シグナル」としてOPENで記録する。以後、価格を定期的に取得して評価損益・勝敗(利確/損切り到達)を自動更新し、その結果をダッシュボード(Web)とLINE/Discordで確認できるようにする。ユーザーが実際に購入した銘柄は別枠(「Myリアル購入ポートフォリオ」)で手動登録し、同様に損益を追跡する。

## アーキテクチャ

```
┌─────────────────────┐     ┌──────────────────────┐
│ GitHub Actions (cron)│     │ FastAPI (server.py)  │
│ ・intraday_alert     │     │ ・GET /              │
│ ・prediction         │     │ ・GET/POST/DELETE    │
│ ・daily_scanner      │     │   /api/history        │
│ ・weekly_performance │     │ ・GET/POST/DELETE    │
└──────────┬───────────┘     │   /api/portfolio       │
           │                 │ ・POST /api/refresh    │
           ▼                 └──────────┬────────────┘
   modules/*  (スキャナー本体)            │
           │                             │
           └──────────┬──────────────────┘
                       ▼
          common/performance_tracker.py
        (シグナル記録・価格更新・成績集計・
         dashboard.html / index.html 生成)
                       │
          ┌────────────┼────────────┐
          ▼                         ▼
  SUPABASE_URL が                data/*.json
  設定されていれば                (ローカル/フォールバック)
  common/database.py
  (Supabase REST, supabase-py)
```

- スキャナー(`modules/*`)とWeb API(`server.py`)は、どちらも同じ`common/performance_tracker.py`の関数を呼ぶだけなので、データの持ち方は完全に一本化されている。
- `dashboard.html`と`index.html`は**生成物**。`generate_html_dashboard()`が呼ばれるたびに同じ内容で両方とも上書きされる(データはインラインJSの`serverHistory`/`serverPortfolio`として埋め込まれる)。直接編集しても次の実行で消える。

## データの永続化

Supabaseが正(single source of truth)。`SUPABASE_URL`/`SUPABASE_KEY`は本番(Render)・GitHub Actions(`daily_scanner`/`prediction`/`weekly_performance`、DBに書き込むワークフローのみ)双方にSecretsとして設定済みで、常にDBへ読み書きする。DB操作が例外を投げた場合のみ`data/signal_history.json`/`data/real_portfolio.json`への書き込みにフォールバックする(ローカルで`SUPABASE_URL`未設定のまま動かす場合も同様にこのJSONフォールバックが使われる)。

`intraday_alert.yml`は通知専用でデータ永続化を一切行わないため、Supabaseの認証情報を渡していない。

`data/cache.json`は上記とは別系統で、常にファイルベースのTTLキャッシュ(マクロ指標・EDINET開示情報などの取得結果をキャッシュし、API叩きすぎを防止)。

過去に`weekly_performance.yml`が`data/signal_history.json`/`dashboard.html`を`main`へ直接push していた時期があり、リポジトリ内の`data/*.json`にはその名残の古いスナップショットが残っている。現在はSupabaseが正なので、これらのファイルは「ローカルでSupabase未設定のまま動かした場合のフォールバック先」以上の意味を持たない。

DB操作が実際にJSONへフォールバックした回(=Supabase接続エラーが起きた回)は、その実行の通知(LINE/Discord)冒頭に「⚠️ Supabase接続エラーのためJSON保存にフォールバックしました」という警告文が自動で付く(`common/performance_tracker.py`の`db_fallback_occurred()`)。フォールバックが黙って発生して気づかない、という事態を防ぐための仕組み。

## シグナルのライフサイクル

1. `record_signal()`でステータス`OPEN`として`entry_price`/`target_price`(利確)/`stop_loss_price`(損切り)付きで記録。
2. `update_signal_performance()`が(サーバー起動時・`/`アクセス時のバックグラウンドタスク・各スキャナー実行時に)yfinanceで現在価格を再取得し、`current_price`/`max_price`/`min_price`/`return_pct`/`pnl_yen`を更新。目標価格到達で`WIN`、損切り価格到達で`LOSS`に遷移。
3. 週次で`generate_weekly_report()`が勝率・累計損益をまとめてLINEに送信。

## スコアリングロジック (`modules/post_analysis/quant_analyzer.py` : `evaluate_quant_factors`)

100点満点、以下7要素の加点方式(上限100点でクリップ):

| 要素 | 内容 | 配点 |
|---|---|---|
| 固有モメンタム | ベンチマーク(`1321.T`)に対する残差モメンタム z-score | 最大+30 |
| ボラティリティ・スクイーズ | TTM Squeeze(ボリンジャー×ケルトナー)解除/継続 | 最大+25 |
| 需給(OBV) | OBVの20日平均超え・出来高急増 | 最大+20 |
| グローバルマクロ | SOX指数(半導体銘柄)/ドル円(輸出銘柄)/VIX低水準 | 最大+15 |
| Xセンチメント | Yahoo!リアルタイム検索の話題度スコア×0.1 | 変動 |
| EDINET開示 | 大量保有報告書(5%ルール)等の検知 | +30 |
| ATRベースの損益ライン | 目標=終値+3×ATR、損切り=終値−2×ATR (リスクリワード比 約1:1.5) | — |

`modules/post_analysis/pro_analyzer.py`は別系統の古い100点スコアラーで、現状どのスキャナーからも呼ばれていない(未使用と思われるが削除はしていない)。

スコア加点には含まれないが、`modules/post_analysis/advanced_scraper.py`の`get_stock_financial_perks()`(yfinance + Kabutanスクレイピング、7日キャッシュ)で配当利回り・株主優待情報も取得し、シグナルの`details`に`配当利回り`/`株主優待`として保存している(スコア条件を満たした銘柄・注目テーマのフォールバック銘柄いずれも)。ダッシュボードの「指標」列に表示される。

既存シグナルへの遡及反映(バックフィル)は`update_signal_performance()`が毎回行う。現在値・PER/PBR/EPS/配当利回り/株主優待は、記録日当日で「記録日以降のローソク足(`df_after`)」がまだ無くても、`yfinance`から取れる最新の終値をそのまま使って反映する。`df_after`はWIN/LOSS判定(利確・損切りラインへの到達チェック)にのみ使い、それが空の間はステータスは`OPEN`/`HOLD 保有中`のまま判定を保留する。

## 自動実行ジョブ(GitHub Actions, `.github/workflows/`)

cron時刻はUTC表記(括弧内がJST)。

| ワークフロー | 実行タイミング | 内容 |
|---|---|---|
| `intraday_alert.yml` | 平日 00:00–06:59 UTC(09:00–15:59 JST) 5分おき | 5分足で出来高急増(前足比10倍以上)＋陽線を検知しアラート通知のみ(シグナル記録はしない) |
| `prediction.yml` | 23:00 UTC(08:00 JST) | 朝の「未来予測」。スコア60点以上 かつ (スクイーズ解除 or 強モメンタム or EDINET開示)でシグナル記録 |
| `daily_scanner.yml` | 06:30 UTC(15:30 JST、大引け後) | 場後の「事後分析」。スコア70点以上でシグナル記録 |
| `weekly_performance.yml` | 土曜 01:00 UTC(10:00 JST) | 週次勝率レポートをLINE送信 |

`daily_scanner`・`prediction`ともに、70点/60点条件を満たす銘柄が1つもなければ「注目テーマTOP3」の代表銘柄をスコア65固定で自動記録するフォールバック動作になっている(ウォッチリストが少ないため、毎日何かしらシグナルが記録される設計)。

`intraday_alert`のみ通知専用でシグナル記録を一切行わない。

対象ウォッチリスト(`daily_scanner.py`/`trend_predictor.py`で共通、コード内に直書き):
`7203 9984 6920 8035 6861 7974 6758 9432 8306 4063 7011 6857`(ベンチマーク: `1321.T` 日経225連動ETF)

### なぜ毎回同じ銘柄が記録されるのか

市場全体から新規候補を探す仕組みは無く、**候補は常にこの12銘柄+フォールバックの2経路だけ**に限定されているため。

1. **スコア条件を満たした場合** — 評価対象自体がこの固定12銘柄のみ(`TARGET_TICKERS`にハードコード)。動的なスクリーニング(出来高上位・値上がり率上位などから毎回対象を選び直す処理)は無いので、スコアが高くなるのも基本的にこの12銘柄の中からだけ。
2. **条件を満たす銘柄が無い場合のフォールバック** — Kabutanの注目テーマページ(`https://kabutan.jp/theme/`)から取得した「注目テーマTOP3」の代表銘柄をスコア65固定で記録する。ただし半導体・AI関連のような人気テーマは長期間上位に居座りやすく、テーマごとの代表銘柄も株探側のページ構成上少数に固定されがちなので、この経路でも同じ銘柄が繰り返し出やすい。

銘柄の顔ぶれを増やしたい場合は、(a) `TARGET_TICKERS`に銘柄を追加する、(b) 出来高急増・値上がり率上位などから毎回対象を動的に選定するスクリーニング処理を新設する、のいずれかの改修が必要(現状はどちらも未実装)。

## Web API (`server.py`)

- `GET /` — ダッシュボードHTML(`index.html`)をそのまま返す。裏でバックグラウンド更新をキック。
- `GET/POST/DELETE /api/history` — AI推奨シグナルのCRUD。POSTは画面から手動で候補銘柄を追加する用(目標/損切りは省略時entry_price×1.06/0.96)。
- `GET/POST/DELETE /api/portfolio` — 実際に購入した銘柄のCRUD(100株固定ではなく`shares`指定可)。
- `POST /api/refresh?force=true|false` — 価格の即時再取得(`force=true`はキャッシュ無視)。

## セットアップ・ローカル起動

```bash
pip install -r requirements.txt
python server.py          # http://localhost:8000
# または
docker-compose up
```

必要な環境変数(`.env`、gitignore済み):

| 変数 | 用途 | 未設定時の挙動 |
|---|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase REST接続 | 未設定なら`data/*.json`にフォールバック |
| `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` | LINE通知 | 未設定ならLINE送信スキップ |
| `DISCORD_WEBHOOK_URL` | Discord通知 | 未設定ならコード内蔵の既定Webhookにフォールバック(要ローテーション、[common/notifier.py](common/notifier.py:11)参照) |

GitHub Actions側は同名のシークレットをリポジトリのSecretsに設定して利用。`SUPABASE_URL`/`SUPABASE_KEY`は`daily_scanner`/`prediction`/`weekly_performance`の3ワークフローに設定(`intraday_alert`はデータ永続化をしないため不要)。

## デプロイ

Render.com(`render.yaml` → `Dockerfile`をビルド、`Procfile`は同等のuvicorn起動コマンド)。本番はSupabaseが永続化先、ローカルはDockerボリューム`./data`が永続化先。
