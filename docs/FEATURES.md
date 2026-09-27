# 機能・API リファレンス

ダッシュボード(Web画面)でできることと、`server.py` が公開している HTTP エンドポイントの一覧。仕組みの全体像・スコア式・cron スケジュールは [README.md](../README.md)、障害時の対応は [operations.md](operations.md) を参照。

画面の実体は `common/performance_tracker.py` の `generate_html_dashboard()` 内のテンプレート。`index.html` / `dashboard.html` は生成物なので、画面を変えるときはテンプレート側を編集する。

---

## 1. 画面(ダッシュボード)

### URL

| URL | 表示される画面 |
|---|---|
| `/` | `/candidates` へリダイレクト |
| `/candidates` | 🤖 AI推奨シグナル(候補)タブ |
| `/portfolio` | 💼 My リアル購入ポートフォリオタブ |

どちらも同じ `index.html` を返し、開くタブは URL のパスでフロント側が決める。タブを切り替えると URL も `/candidates` ⇔ `/portfolio` に書き換わるので、ブックマークすればそのタブから開ける。ページを開くたびに裏で株価更新(10分キャッシュ)が走る。

### 共通ヘッダー

| 要素 | 内容 |
|---|---|
| 更新バッジ | HTML を最後に生成した時刻 |
| 🔄 データ再読み込み | キャッシュを無視して最新株価を取り直す(`POST /api/refresh?force=true`)。取得中は各行が「🔄 取得中」表示になる |

### 🤖 AI推奨シグナルタブ

スキャナーが自動記録したシグナルと、自分で追加した「見たい候補」を同じ表で追跡する。

**集計カード**

| カード | 中身 |
|---|---|
| 目標勝率 | 決着済みのうち WIN(利確到達)の割合と、WIN/LOSS 件数 |
| 最新評価損益 (100株計) | 全シグナルを 100 株ずつ持った想定での評価損益合計と通算リターン |
| 総シグナル数 | 全件数と監視中(OPEN)件数 |

**損益の起点セレクタ**

「開始日(登録時)から / 前営業日から / 1週間前から / 1ヶ月前から」を切り替えると、表の開始時株価・損益・WIN/LOSS 判定がその起点基準で表示し直される。

- 1週間前 = 5営業日前、1ヶ月前 = 20営業日前の終値。
- 利確/損切りラインは開始時株価からの比率を保ったまま起点株価に引き直し、「その起点から今日までにラインへ届いたか」を起点ごとに判定する(サーバ側で計算した `basis_results` を使用)。
- 選んだ起点はブラウザ(localStorage)に記憶される。

**表の列**

企業名(業種またはテーマのラベル付き)/ スコア / 開始時株価(100株購入額)/ 最新株価と差額 / 目標利確・損切り / 100株損益額(%)/ ステータス(`OPEN 監視中`・`WIN 利確到達`・`LOSS 損切到達`)/ 開始日時・決着日時 / 指標(PER・PBR・EPS・配当利回り・株主優待・ATR・テーマ)/ 削除ボタン

**操作**

| 操作 | やり方 | 呼ぶAPI |
|---|---|---|
| 候補を手動追加 | 「➕ 画面から推奨候補銘柄を追加」→ 開始日時・コード・企業名(空なら自動取得)・開始時株価・目標利確/損切り(空なら ×1.06 / ×0.96)・テーマを入力 | `POST /api/history` |
| 株価チャートを見る | 行をタップ(チェックボックスとボタン以外)。直近6ヶ月の終値に、起点・利確・損切りの水平線を重ねて表示 | `GET /api/chart/{code}` |
| 開始日時の一括やり直し | 行のチェックボックスで選択 → 日時を指定 →「選択銘柄をこの日時で開始し直す」。その日の終値を開始時株価として取り直し、利確/損切りラインも同じ比率で付け直し、ステータスを OPEN に戻す。決着済みの銘柄を再追跡したいときもこれを使う | `POST /api/history/bulk-start-date` |
| 選択した候補を削除 | チェックして「🗑 選択した候補を削除」 | `POST /api/history/bulk-delete` |
| 全件削除 | 「🗑 候補を全件削除」(確認ダイアログあり、元に戻せない) | `POST /api/history/bulk-delete` (`all: true`) |
| 1件削除 | 行の「削除」 | `DELETE /api/history/{id}` |

### 💼 My リアル購入ポートフォリオタブ

実際に買った銘柄を登録して損益を追う。AI推奨とは別枠。

**集計カード**: 総投資金額(買付単価 × 株数の合計)/ 買付日時からの評価損益合計

**表の列**: 企業名 / スコア / 買付単価(購入額)/ 最新株価と差額 / 目標利確・損切り / 損益額(%)/ ステータス(`HOLD 保有中`・`WIN`・`LOSS`)/ 購入日時・決着日時 / 指標 / 削除ボタン

**操作**

| 操作 | やり方 | 呼ぶAPI |
|---|---|---|
| 購入銘柄を追加 | 「➕ 画面から購入銘柄を即時追加」→ コード・企業名・購入日時・買付単価・株数(既定100)を入力 | `POST /api/portfolio` |
| AI推奨候補から選んで入力 | 追加画面上部のプルダウンで候補を選ぶと、コード・企業名・購入日時(候補の開始日時)が自動入力される | `GET /api/history` |
| 購入日の終値を自動セット | 購入日時を入れると、その日(以前で直近の営業日)の終値を買付単価に入れる。手で上書き可 | `GET /api/close-price` |
| 削除 | 行の「削除」 | `DELETE /api/portfolio/{id}` |

利確/損切りラインは登録時に買付単価 ×1.06 / ×0.96 で自動設定される(画面からは変更できない)。

### 画面に無い機能

- **ウォッチリスト(スキャン対象銘柄)の閲覧・追加・削除**は画面が無く、API(`/api/watchlist`)からのみ操作できる。

---

## 2. API エンドポイント (`server.py`)

- ベースURL: ローカルは `http://localhost:8000`、本番は Render のURL。
- **認証は無い**。URL を知っていれば誰でも追加・削除できる点に注意。
- FastAPI の自動ドキュメント(`/docs`、`/redoc`)も有効なので、ブラウザから試せる。
- データの保存先は Supabase(未設定・接続エラー時は `data/*.json`)。書き込み系は完了後に HTML の再生成や株価更新をバックグラウンドで行う。

### 一覧

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/` | `/candidates` へリダイレクト |
| GET | `/candidates` | 候補タブのHTML |
| GET | `/portfolio` | ポートフォリオタブのHTML |
| GET | `/api/history` | AI推奨シグナル一覧 |
| POST | `/api/history` | シグナルを1件追加 |
| POST | `/api/history/bulk-start-date` | 選択シグナルの開始日時を一括変更 |
| POST | `/api/history/bulk-delete` | 選択 or 全シグナルを削除 |
| DELETE | `/api/history/{signal_id}` | シグナルを1件削除 |
| GET | `/api/portfolio` | リアル購入銘柄一覧 |
| POST | `/api/portfolio` | 購入銘柄を1件追加 |
| DELETE | `/api/portfolio/{index_or_id}` | 購入銘柄を1件削除 |
| GET | `/api/close-price` | 指定日の終値 |
| GET | `/api/chart/{code}` | チャート用の株価時系列 |
| GET | `/api/watchlist` | スキャン対象ウォッチリスト |
| POST | `/api/watchlist` | ウォッチリストに追加 |
| DELETE | `/api/watchlist/{ticker}` | ウォッチリストから削除 |
| POST | `/api/refresh` | 株価の再取得をキック |

### AI推奨シグナル

#### `GET /api/history`
全シグナルを配列で返す。主なフィールド: `id`, `date`(`MM-DD HH:MM`), `ticker_code`, `name`, `score`, `entry_price`, `target_price`, `stop_loss_price`, `current_price`, `max_price`, `min_price`, `return_pct`, `pnl_yen`(100株換算), `status`(`OPEN`/`WIN`/`LOSS`), `closed_at`, `channel`(記録経路。手動は `manual`), `details`(PER/配当利回り/株主優待/Theme など), `ref_prices`(`1d`/`1w`/`1m` の起点株価), `basis_results`(起点ごとの判定結果)。

#### `POST /api/history`
```json
{
  "ticker": "7203",
  "name": "トヨタ自動車",
  "entry_price": 3000,
  "target_price": 3180,
  "stop_loss_price": 2880,
  "score": 75,
  "date": "2026-09-26 15:30",
  "theme": "自分で見たい候補"
}
```
必須は `ticker` と `entry_price`。省略時: `name` は銘柄コードから自動取得、`target_price` = `entry_price` × 1.06、`stop_loss_price` = × 0.96、`score` = 75、`date` = 現在時刻、`theme` = 「手動追加候補」。`.T` は付けても外される。レスポンス: `{"status": "success", "added": {...}}`。

#### `POST /api/history/bulk-start-date`
```json
{ "ids": ["7203_20260926_153000"], "date": "2026-09-01T15:30" }
```
`date` は `YYYY-MM-DDTHH:MM` か `MM-DD HH:MM`。前者の場合はその日(以前で直近)の終値を取り直して `entry_price` にし、利確/損切りラインを元の比率で付け直す。どちらの形式でもステータスは `OPEN` に戻る。レスポンス: `{"status": "success", "updated": [id...], "date": "09-01 15:30"}`。

#### `POST /api/history/bulk-delete`
```json
{ "ids": ["7203_20260926_153000"] }
```
または `{ "all": true }` で全件削除。`ids` には配列の位置(インデックス)も使える。レスポンス: `{"status": "success", "deleted": 件数, "remaining": 残件数}`。

#### `DELETE /api/history/{signal_id}`
`id` が一致するものを削除。一致しなければ配列インデックスとして解釈する。

### リアル購入ポートフォリオ

#### `GET /api/portfolio`
全保有銘柄の配列。主なフィールド: `id`, `ticker`, `name`, `buy_date`, `buy_price`, `shares`, `current_price`, `eval_amount`, `pnl_yen`, `pnl_pct`, `target_price`, `stop_loss_price`, `status`(`HOLD 保有中` 等), `closed_at`, `details`。

#### `POST /api/portfolio`
```json
{ "ticker": "7203", "name": "トヨタ自動車", "buy_price": 3000, "shares": 100, "buy_date": "2026-09-26 10:15" }
```
必須は `ticker`, `buy_price`, `buy_date`。`shares` の既定は 100。利確/損切りは `buy_price` × 1.06 / × 0.96 で自動設定。

#### `DELETE /api/portfolio/{index_or_id}`
`id` 一致、なければ配列インデックスで削除。

### 株価データ

#### `GET /api/close-price?code=7203&date=2026-09-01`
指定日(以前で直近の営業日)の終値。`date` は `YYYY-MM-DD` / `YYYY-MM-DD HH:MM` / `YYYY-MM-DDTHH:MM`。形式が不正なら 400。取れなければ `close: null`。
```json
{ "code": "7203", "date": "2026-09-01", "close": 2987.5 }
```

#### `GET /api/chart/{code}?period=6mo`
日足の `dates` / `closes` / `highs` / `lows` を返す(yfinance、`period` は yfinance の期間指定)。銘柄・期間ごとに30分キャッシュ。取得失敗時は空配列。

### ウォッチリスト

スキャナー(`daily_scanner` / `prediction`)が評価する銘柄の一覧。各要素は `{ticker, tier, added_at, reason}`。`tier` は `core`(固定、自動循環の対象外)か `rotation`(`universe_rotator` による入れ替え対象)。

#### `GET /api/watchlist`
全銘柄の配列。

#### `POST /api/watchlist`
```json
{ "ticker": "7203", "tier": "rotation", "reason": "手動追加" }
```
`.T` は無ければ付与される。既に登録済みなら何もしない。`tier` が `core`/`rotation` 以外なら `rotation` 扱い。レスポンス: `{"status": "ok", "watchlist": [...]}`。

#### `DELETE /api/watchlist/{ticker}`
該当銘柄を削除し、更新後の全件を返す。

### 更新

#### `POST /api/refresh?force=false`
全シグナル・保有銘柄の株価再取得と損益・WIN/LOSS 判定をバックグラウンドで開始し、すぐ返る。`force=false` は10分キャッシュが有効ならそれを使い、`force=true` はキャッシュを無視して取り直す。レスポンス: `{"status": "success", "forced": false, "time": "..."}`。
