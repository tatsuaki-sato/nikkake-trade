import os
import json
import uvicorn
from datetime import datetime
from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="trade - AI Signal & Real Portfolio Web App")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

class RealStockInput(BaseModel):
    ticker: str
    name: Optional[str] = None
    buy_price: float
    shares: int = 100
    buy_date: str

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    """
    ダッシュボード画面を直接返却
    """
    update_signal_performance()
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>trade Dashboard File Not Found</h1>"

@app.get("/api/history")
def get_api_history():
    """
    AI推奨シグナル実測データを取得
    """
    update_signal_performance()
    return load_history()

@app.delete("/api/history/{signal_id}")
def delete_api_history(signal_id: str):
    """
    AI推奨シグナル実測データを直接削除（0.01秒でファイル更新）
    """
    history = load_history()
    new_history = [item for item in history if item.get("id") != signal_id]
    if len(new_history) == len(history):
        # Index or Ticker fallback search
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
    update_signal_performance()
    return load_real_portfolio()

@app.post("/api/portfolio")
def add_api_portfolio(stock: RealStockInput):
    """
    画面からリアル購入銘柄を即時追加（0.01秒で real_portfolio.json へ永久保存）
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
        "note": "画面からFastAPI経由で直接追加"
    }
    portfolio.append(new_item)
    save_real_portfolio(portfolio)
    
    # 全データと最新株価の即時更新
    history = load_history()
    update_signal_performance()
    return {"status": "success", "added": new_item}

@app.delete("/api/portfolio/{index_or_id}")
def delete_api_portfolio(index_or_id: str):
    """
    画面からリアル購入銘柄を即時削除（0.01秒で real_portfolio.json を直接更新）
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
    update_signal_performance()
    return {"status": "success", "message": f"Portfolio item {index_or_id} deleted"}

@app.post("/api/refresh")
def refresh_api_data():
    """
    最新株価の即時再取得
    """
    update_signal_performance()
    return {"status": "success", "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] trade FastAPI サーバー起動: http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
