"""
common/watchlist.py
スキャン対象ウォッチリストの唯一の入口。

これまで daily_scanner / trend_predictor / intraday_alert に重複ハードコード
されていた TARGET_TICKERS をここに一元化する。優先順位は
Supabase `watchlist` テーブル → data/watchlist.json → コード内デフォルト。
(performance_tracker と同じフォールバック思想。DB未設定のローカル/CI環境でも動く)

各銘柄は dict で保持する:
  ticker   : "7203.T" 形式
  tier     : 常に "rotation"。以前の "core"(手動固定枠)は 2026-09-27 に廃止し、
             読み込み時に "rotation" として扱う。入れ替えの対象外になるのは
             「実際に保有中の銘柄」(リアル購入ポートフォリオ、`get_held_tickers()`)だけ。
  added_at : ISO日付
  reason   : いつ・なぜ入ったか
"""
import os
import json
from datetime import datetime

WATCHLIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watchlist.json"
)

# 従来の固定12銘柄。DBもJSONも無い環境でのフォールバック(挙動の後方互換)。
DEFAULT_WATCHLIST = [
    {"ticker": t, "tier": "rotation", "added_at": "2026-08-22", "reason": "初期固定リスト"}
    for t in [
        "7203.T", "8035.T", "6758.T", "8306.T", "9432.T",
        "9984.T", "6920.T", "6861.T", "7974.T", "4063.T", "7011.T", "6857.T",
    ]
]

def _use_db() -> bool:
    return bool(os.environ.get("SUPABASE_URL"))

def _normalize(items: list) -> list:
    """廃止した "core" 枠を含む旧データを "rotation" に揃える"""
    for i in items:
        i["tier"] = "rotation"
    return items

def load_watchlist() -> list:
    """ウォッチリスト全件(dictのリスト)を返す。空にはならない。"""
    return _normalize(_load_raw())

def _load_raw() -> list:
    if _use_db():
        try:
            from common.database import db_load_watchlist
            items = db_load_watchlist()
            if items:
                return items
        except Exception as e:
            print(f"⚠️ watchlist DB読込失敗、ローカルへフォールバック: {e}")
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
                if items:
                    return items
    except Exception as e:
        print(f"⚠️ watchlist JSON読込失敗: {e}")
    return [dict(item) for item in DEFAULT_WATCHLIST]

def save_watchlist(items: list):
    """全件保存(DB優先、失敗時はJSON)。JSONにも常にミラーする。"""
    if _use_db():
        try:
            from common.database import db_save_watchlist
            db_save_watchlist(items)
        except Exception as e:
            print(f"⚠️ watchlist DB保存失敗: {e}")
    try:
        os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ watchlist JSON保存失敗: {e}")

def get_target_tickers() -> list:
    """スキャナー用: "7203.T" 形式のティッカー一覧"""
    return [item["ticker"] for item in load_watchlist()]

def get_held_tickers() -> set:
    """実際に保有中の銘柄(リアル購入ポートフォリオに登録されている銘柄)を
    "7203.T" 形式で返す。ローテーターはこれらを入れ替え対象外にする。

    ポートフォリオの WIN/LOSS 表示は目標・損切りラインに触れたという判定で、
    売却したことを意味しないため、ステータスに関係なく登録中なら保有扱い。
    売ったらユーザーがポートフォリオから削除する運用。"""
    from common.performance_tracker import load_real_portfolio, db_fallback_occurred
    portfolio = load_real_portfolio()
    if db_fallback_occurred():
        # DB読込に失敗してローカルJSON(CIでは空)に逃げた場合、保有銘柄を
        # 取りこぼしたまま入れ替えることになるので、呼び出し側に失敗を伝える
        raise RuntimeError("リアル購入ポートフォリオをDBから読めませんでした")
    held = set()
    for p in portfolio:
        code = str(p.get("ticker", "")).replace(".T", "").strip()
        if code:
            held.add(f"{code}.T")
    return held

def add_ticker(ticker: str, tier: str = "rotation", reason: str = "手動追加") -> list:
    """1銘柄追加(既存なら何もしない)。更新後の全件を返す。
    tier は後方互換のため受け取るが、常に "rotation" として保存する。"""
    if not ticker.endswith(".T"):
        ticker = f"{ticker}.T"
    items = load_watchlist()
    if any(i["ticker"] == ticker for i in items):
        return items
    items.append({
        "ticker": ticker,
        "tier": "rotation",
        "added_at": datetime.now().strftime("%Y-%m-%d"),
        "reason": reason,
    })
    save_watchlist(items)
    return items

def remove_ticker(ticker: str) -> list:
    """1銘柄削除。更新後の全件を返す。"""
    if not ticker.endswith(".T"):
        ticker = f"{ticker}.T"
    items = [i for i in load_watchlist() if i["ticker"] != ticker]
    save_watchlist(items)
    return items
