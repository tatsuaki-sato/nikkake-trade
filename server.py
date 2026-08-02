import os
import json
import uvicorn
import threading
from datetime import datetime
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

app = FastAPI(title="nikkake-trade - AI Signal & Real Portfolio Web App")

@app.on_event("startup")
async def startup_event():
    """
    サーバー起動時に自動でyfinance株価取得・損益更新を実行（バックグラウンド）
    これにより current_price / pnl_yen が常に最新になる
    """
    def run_update():
        try:
            update_signal_performance(force_refresh=True)
        except Exception as e:
            print(f"Startup update error: {e}")
    threading.Thread(target=run_update, daemon=True).start()

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
        "details": {
            "Theme": signal.theme if signal.theme else "手動追加候補"
        }
    }
    history.append(new_item)
    save_history(history)
    
    background_tasks.add_task(update_signal_performance, True)
    return {"status": "success", "added": new_item}

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
        "details": {
            "PER": "15.0倍",
            "PBR": "1.1倍",
            "ATR": f"±{round(stock.buy_price * 0.02)}円"
        },
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
