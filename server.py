import os
import json
import uvicorn
import threading
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from common.performance_tracker import (
    load_history, save_history,
    load_real_portfolio, save_real_portfolio,
    update_signal_performance, generate_html_dashboard
)
from common.stock_names import get_company_name
from common.watchlist import load_watchlist, add_ticker, remove_ticker

def fetch_close_on(code: str, target_dt: datetime):
    """指定日(以前で直近)の終値を返す。取得できなければ None。"""
    try:
        import yfinance as yf
        import pandas as pd
        end = target_dt + timedelta(days=1)
        start = target_dt - timedelta(days=10)
        df = yf.download(f"{code}.T", start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if getattr(df.columns, "nlevels", 1) > 1:
            df.columns = df.columns.get_level_values(0)
        return round(float(df["Close"].dropna().iloc[-1]), 1)
    except Exception as e:
        print(f"開始時株価の再取得に失敗 ({code}): {e}")
        return None

app = FastAPI(title="nikkake-trade - AI Signal & Real Portfolio Web App")

@app.on_event("startup")
async def startup_event():
    """
    サーバー起動時:
    1. SupabaseのDBテーブルを自動作成（初回のみ）
    2. yfinance株価取得・損益更新をバックグラウンド実行
    """
    def run_startup():
        try:
            # DB初期化（SUPABASE_URLが設定されている場合のみ）
            if os.environ.get("SUPABASE_URL"):
                from common.database import init_db
                init_db()
        except Exception as e:
            print(f"DB init error: {e}")
        try:
            update_signal_performance(force_refresh=True)
        except Exception as e:
            print(f"Startup update error: {e}")
    threading.Thread(target=run_startup, daemon=True).start()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

class RealStockInput(BaseModel):
    ticker: str
    name: Optional[str] = None
    buy_price: float
    shares: int = 100
    buy_date: str

class AISignalInput(BaseModel):
    ticker: str
    name: Optional[str] = None
    entry_price: float
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    score: int = 75
    date: Optional[str] = None
    theme: Optional[str] = None

class WatchlistInput(BaseModel):
    ticker: str
    tier: str = "rotation"
    reason: str = "手動追加"

@app.get("/api/watchlist")
def get_api_watchlist():
    """スキャン対象ウォッチリストを取得"""
    return load_watchlist()

@app.post("/api/watchlist")
def add_api_watchlist(item: WatchlistInput):
    """ウォッチリストに銘柄を追加"""
    items = add_ticker(item.ticker, tier=item.tier, reason=item.reason)
    return {"status": "ok", "watchlist": items}

@app.delete("/api/watchlist/{ticker}")
def delete_api_watchlist(ticker: str):
    """ウォッチリストから銘柄を削除"""
    items = remove_ticker(ticker)
    return {"status": "ok", "watchlist": items}

@app.get("/", response_class=HTMLResponse)
def get_dashboard(background_tasks: BackgroundTasks):
    """
    画面を0.01秒で即時返却（10分間キャッシュ有効、アクセス回数削減）
    """
    background_tasks.add_task(update_signal_performance, False)
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>nikkake-trade Dashboard File Not Found</h1>"

@app.get("/api/history")
def get_api_history():
    """
    AI推奨シグナル実測データを取得（0.01秒爆速返却）
    """
    return load_history()

@app.post("/api/history")
def add_api_history(signal: AISignalInput, background_tasks: BackgroundTasks):
    """
    画面から推奨候補銘柄を即時追加（0.01秒保存）
    """
    code = signal.ticker.replace('.T', '').strip()
    name = signal.name.strip() if signal.name and signal.name.strip() else get_company_name(code)
    entry_p = signal.entry_price
    target_p = signal.target_price if signal.target_price else round(entry_p * 1.06, 1)
    stop_p = signal.stop_loss_price if signal.stop_loss_price else round(entry_p * 0.96, 1)
    now_str = signal.date if signal.date else datetime.now().strftime("%m-%d %H:%M")

    history = load_history()
    new_item = {
        "id": f"{code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "date": now_str,
        "ticker_code": code,
        "name": name,
        "entry_price": entry_p,
        "sim_amount": entry_p * 100,
        "target_price": target_p,
        "stop_loss_price": stop_p,
        "score": signal.score,
        "status": "OPEN",
        "closed_at": "-",
        "current_price": entry_p,
        "max_price": entry_p,
        "min_price": entry_p,
        "return_pct": 0.0,
        "pnl_yen": 0.0,
        "channel": "manual",
        "details": {
            "Theme": signal.theme if signal.theme else "手動追加候補"
        }
    }
    history.append(new_item)
    save_history(history)
    background_tasks.add_task(update_signal_performance, True)
    return {"status": "success", "added": new_item}

class BulkStartDateInput(BaseModel):
    ids: list
    date: str  # "YYYY-MM-DDTHH:MM" (datetime-local) または "MM-DD HH:MM"

@app.post("/api/history/bulk-start-date")
def bulk_update_start_date(payload: BulkStartDateInput, background_tasks: BackgroundTasks):
    """選択した銘柄の開始日時をまとめて更新する。

    開始日時だけ動かすと「開始時株価」が別の日の値のまま残り損益が意味を成さないので、
    その日の終値を取り直して開始時株価も揃える(取得できない銘柄は日時のみ更新)。
    追跡をやり直す操作なので、判定状態もOPENに戻す。
    """
    raw = payload.date.strip().replace("T", " ")
    try:
        base_dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        display = base_dt.strftime("%m-%d %H:%M")
    except ValueError:
        base_dt = None
        display = raw

    history = load_history()
    targets = {str(i) for i in payload.ids}
    updated = []
    for item in history:
        if str(item.get("id")) not in targets:
            continue
        item["date"] = display
        item["status"] = "OPEN"
        item["closed_at"] = "-"
        if base_dt:
            code = item.get("ticker_code") or item.get("ticker", "")
            new_price = fetch_close_on(str(code).replace(".T", ""), base_dt)
            if new_price:
                item["entry_price"] = new_price
                item["sim_amount"] = new_price * 100
                item["current_price"] = new_price
                item["max_price"] = new_price
                item["min_price"] = new_price
                item["return_pct"] = 0.0
                item["pnl_yen"] = 0.0
        updated.append(item.get("id"))

    save_history(history)
    background_tasks.add_task(update_signal_performance, True)
    return {"status": "success", "updated": updated, "date": display}

@app.delete("/api/history/{signal_id}")
def delete_api_history(signal_id: str):
    """
    AI推奨シグナル実測データを直接削除
    """
    history = load_history()
    new_history = [item for item in history if item.get("id") != signal_id]
    if len(new_history) == len(history):
        try:
            idx = int(signal_id)
            if 0 <= idx < len(history):
                new_history = [item for i, item in enumerate(history) if i != idx]
        except ValueError:
            pass
            
    save_history(new_history)
    real_portfolio = load_real_portfolio()
    generate_html_dashboard(new_history, real_portfolio)
    return {"status": "success", "message": f"Signal {signal_id} deleted", "remaining": len(new_history)}

@app.get("/api/portfolio")
def get_api_portfolio():
    """
    リアル購入ポートフォリオデータを取得
    """
    return load_real_portfolio()

@app.post("/api/portfolio")
def add_api_portfolio(stock: RealStockInput, background_tasks: BackgroundTasks):
    """
    画面からリアル購入銘柄を即時追加
    """
    code = stock.ticker.replace('.T', '').strip()
    name = stock.name.strip() if stock.name and stock.name.strip() else get_company_name(code)
    
    portfolio = load_real_portfolio()
    new_item = {
        "id": f"real_{code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "ticker": code,
        "name": name,
        "buy_date": stock.buy_date.replace('T', ' '),
        "buy_price": stock.buy_price,
        "shares": stock.shares,
        "current_price": stock.buy_price,
        "eval_amount": stock.buy_price * stock.shares,
        "pnl_yen": 0.0,
        "pnl_pct": 0.0,
        "target_price": round(stock.buy_price * 1.06, 1),
        "stop_loss_price": round(stock.buy_price * 0.96, 1),
        "status": "HOLD 保有中",
        "closed_at": "-",
        "details": {},
        "note": "画面からFastAPI経由で直接追加"
    }
    portfolio.append(new_item)
    save_real_portfolio(portfolio)
    background_tasks.add_task(update_signal_performance, True)
    return {"status": "success", "added": new_item}

@app.delete("/api/portfolio/{index_or_id}")
def delete_api_portfolio(index_or_id: str):
    """
    画面からリアル購入銘柄を即時削除
    """
    portfolio = load_real_portfolio()
    new_portfolio = [item for item in portfolio if item.get("id") != index_or_id]
    
    if len(new_portfolio) == len(portfolio):
        try:
            idx = int(index_or_id)
            if 0 <= idx < len(portfolio):
                new_portfolio = [item for i, item in enumerate(portfolio) if i != idx]
        except ValueError:
            pass
            
    save_real_portfolio(new_portfolio)
    history = load_history()
    generate_html_dashboard(history, new_portfolio)
    return {"status": "success", "message": f"Portfolio item {index_or_id} deleted"}

@app.post("/api/refresh")
def refresh_api_data(background_tasks: BackgroundTasks, force: bool = False):
    """
    最新株価の即時再取得（右上のボタンクリック時のみ force=True）
    """
    background_tasks.add_task(update_signal_performance, force)
    return {"status": "success", "forced": force, "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] nikkake-trade FastAPI サーバー起動: http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
