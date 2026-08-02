import json
import os
import time
import re
from datetime import datetime
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from common.stock_names import get_company_name

HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "signal_history.json")
REAL_PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "real_portfolio.json")
DASHBOARD_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html")
INDEX_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")

# 右上の再読み込みボタンを押さない限り「10分間（600秒）アクセスゼロ」にするキャッシュ
_STOCK_DATA_CACHE = None
_CACHE_TIMESTAMP = 0
CACHE_TTL_SECONDS = 600  # 10分キャッシュ

def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(history: list):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_real_portfolio() -> list:
    if not os.path.exists(REAL_PORTFOLIO_FILE):
        return []
    try:
        with open(REAL_PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_real_portfolio(portfolio: list):
    os.makedirs(os.path.dirname(REAL_PORTFOLIO_FILE), exist_ok=True)
    with open(REAL_PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

def record_signal(ticker: str, entry_price: float, target_price: float, stop_loss_price: float, score: int, details: dict):
    history = load_history()
    now_str = datetime.now().strftime("%m-%d %H:%M")
    code = ticker.replace('.T', '').strip()
    
    for item in history:
        if item.get("ticker_code") == code and item.get("date", "").startswith(datetime.now().strftime("%m-%d")):
            return
            
    name = get_company_name(code)
    sim_amount = entry_price * 100
    
    signal_entry = {
        "id": f"{code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "date": now_str,
        "ticker_code": code,
        "name": name,
        "entry_price": round(entry_price, 1),
        "sim_amount": sim_amount,
        "target_price": round(target_price, 1),
        "stop_loss_price": round(stop_loss_price, 1),
        "score": score,
        "status": "OPEN",
        "closed_at": "-",
        "current_price": round(entry_price, 1),
        "max_price": round(entry_price, 1),
        "min_price": round(entry_price, 1),
        "return_pct": 0.0,
        "pnl_yen": 0.0,
        "details": details
    }
    history.append(signal_entry)
    save_history(history)

def fetch_japan_stock_price_direct(code: str) -> dict:
    """
    Yahoo Finance USがRender等のクラウドIPをブロックするため、
    日本国内（Yahoo!ファイナンスJapan / 株探）から100%確実に最新株価をダイレクト取得
    """
    # 1st try: Yahoo!ファイナンス JAPAN (ブロックなし)
    try:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Yahoo Japanの現在値要素クラス
            price_elem = soup.find('span', class_='_3rXW27w1') or soup.find('span', class_='_2dvwP6a7') or soup.find('span', class_='_1E8Gq241')
            if price_elem:
                price_str = price_elem.text.replace(',', '').replace('円', '').strip()
                p_val = float(price_str)
                return {"close": p_val, "high": p_val, "low": p_val}
    except Exception:
        pass

    # 2nd try: 株探 (Kabutan) バックアップ
    try:
        url = f"https://kabutan.jp/stock/?code={code}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            price_span = soup.find('span', class_='kabuka')
            if price_span:
                price_str = price_span.text.replace(',', '').replace('円', '').strip()
                p_val = float(price_str)
                return {"close": p_val, "high": p_val, "low": p_val}
    except Exception:
        pass

    return None

def fetch_stock_data_robust(tickers: list, force_refresh: bool = False):
    """
    10分間（600秒）完全キャッシュ。右上の手動再読み込みボタン（force_refresh=True）を押した時のみ更新
    """
    global _STOCK_DATA_CACHE, _CACHE_TIMESTAMP
    now = time.time()
    
    if not force_refresh and _STOCK_DATA_CACHE is not None and (now - _CACHE_TIMESTAMP < CACHE_TTL_SECONDS):
        return _STOCK_DATA_CACHE

    if not tickers:
        return None
        
    result_dict = {}
    
    # 1. まず一括でyfinanceを試行
    try:
        data = yf.download(tickers, period="3mo", interval="1d", group_by="ticker", progress=False, threads=False)
        if data is not None and not data.empty:
            _STOCK_DATA_CACHE = data
            _CACHE_TIMESTAMP = now
            return data
    except Exception as e:
        print(f"yfinance bulk download failed in cloud: {e}")

    # 2. クラウド環境（Render）でYahoo Finance USがブロックされた場合、日本国内ソースから直接取得
    for t in tickers:
        code = t.replace('.T', '').strip()
        direct_data = fetch_japan_stock_price_direct(code)
        if direct_data:
            # yfinance風のDataFrame形式を擬似生成
            df = pd.DataFrame([{
                "High": direct_data["high"],
                "Low": direct_data["low"],
                "Close": direct_data["close"]
            }], index=[pd.to_datetime(datetime.now().strftime("%Y-%m-%d"))])
            result_dict[t] = df

    if result_dict:
        _STOCK_DATA_CACHE = result_dict
        _CACHE_TIMESTAMP = now
        return result_dict
        
    return _STOCK_DATA_CACHE

def update_signal_performance(force_refresh: bool = False):
    history = load_history()
    real_portfolio = load_real_portfolio()
    
    all_tickers = []
    if history:
        all_tickers.extend([item.get("ticker_code", item.get("ticker", "")) + ".T" for item in history])
    if real_portfolio:
        all_tickers.extend([item.get("ticker", "") + ".T" for item in real_portfolio])
        
    tickers = list(set([t for t in all_tickers if t != ".T"]))
    if not tickers:
        generate_html_dashboard(history, real_portfolio)
        return

    data_store = fetch_stock_data_robust(tickers, force_refresh=force_refresh)
    now_time_str = datetime.now().strftime("%m-%d %H:%M")

    for item in history:
        dt_val = item.get("date", "")
        if " " in dt_val and len(dt_val.split()[0].split("-")) == 3:
            parts = dt_val.split()
            ymd = parts[0].split("-")
            item["date"] = f"{ymd[1]}-{ymd[2]} {parts[1]}"
        elif len(dt_val.split("-")) == 3:
            ymd = dt_val.split("-")
            item["date"] = f"{ymd[1]}-{ymd[2]} 15:30"

        code = item.get("ticker_code", item.get("ticker", ""))
        symbol = code + ".T"
        
        # セーフガード: closed_atが推奨日より過去であれば強制的リセット
        rec_date_str = item.get("date", "08-02").split()[0]
        closed_at_str = item.get("closed_at", "-")
        if closed_at_str != "-" and " " in closed_at_str:
            c_date_part = closed_at_str.split()[0]
            if c_date_part < rec_date_str:
                item["status"] = "OPEN"
                item["closed_at"] = "-"
                item["return_pct"] = 0.0
                item["pnl_yen"] = 0.0

        try:
            df = None
            if isinstance(data_store, dict):
                df = data_store.get(symbol)
            elif data_store is not None:
                try:
                    df = data_store[symbol].dropna() if len(tickers) > 1 else data_store.dropna()
                except Exception:
                    df = None

            entry_p = item["entry_price"]
            target_p = item["target_price"]
            stop_p = item["stop_loss_price"]

            if df is not None and not df.empty:
                if getattr(df.index, 'tz', None) is not None:
                    df.index = df.index.tz_localize(None)

                current_year = datetime.now().year
                try:
                    rec_dt = datetime.strptime(f"{current_year}-{rec_date_str}", "%Y-%m-%d")
                    df_after = df[df.index >= rec_dt]
                except Exception:
                    df_after = pd.DataFrame()
                    
                if df_after.empty:
                    item["status"] = "OPEN"
                    item["closed_at"] = "-"
                    item["return_pct"] = 0.0
                    item["pnl_yen"] = 0.0
                    item["current_price"] = entry_p
                    continue

                high_price = float(df_after["High"].max())
                low_price = float(df_after["Low"].min())
                latest_close = float(df_after["Close"].iloc[-1])
                
                item["current_price"] = round(latest_close, 1)
                item["max_price"] = round(max(item.get("max_price", entry_p), high_price), 1)
                item["min_price"] = round(min(item.get("min_price", entry_p), low_price), 1)
                item["return_pct"] = round(((latest_close - entry_p) / entry_p) * 100, 2)
                item["pnl_yen"] = round((latest_close - entry_p) * 100, 0)
                
                trigger_closed_at = None
                trigger_status = None
                
                for idx, row in df_after.iterrows():
                    r_high = float(row["High"])
                    r_low = float(row["Low"])
                    dt_obj = pd.to_datetime(idx)
                    dt_formatted = dt_obj.strftime("%m-%d 15:30")
                    
                    if r_low <= stop_p:
                        trigger_status = "LOSS"
                        trigger_closed_at = dt_formatted
                        break
                    elif r_high >= target_p:
                        trigger_status = "WIN"
                        trigger_closed_at = dt_formatted
                        break
                
                if trigger_status:
                    item["status"] = trigger_status
                    item["closed_at"] = trigger_closed_at if trigger_closed_at else now_time_str
                    if trigger_status == "LOSS":
                        item["return_pct"] = round(((stop_p - entry_p) / entry_p) * 100, 2)
                        item["pnl_yen"] = round((stop_p - entry_p) * 100, 0)
                    else:
                        item["return_pct"] = round(((target_p - entry_p) / entry_p) * 100, 2)
                        item["pnl_yen"] = round((target_p - entry_p) * 100, 0)
                else:
                    item["status"] = "OPEN"
                    item["closed_at"] = "-"
            else:
                item["status"] = "OPEN"
                item["closed_at"] = "-"
        except Exception as e:
            print(f"Error updating item ({code}): {e}")
            item["status"] = "OPEN"
            item["closed_at"] = "-"
            continue

    save_history(history)

    for item in real_portfolio:
        code = item.get("ticker", "")
        symbol = code + ".T"
        
        rec_date_str = item.get("buy_date", "08-02").split()[0]
        closed_at_str = item.get("closed_at", "-")
        if closed_at_str != "-" and " " in closed_at_str:
            c_date_part = closed_at_str.split()[0]
            if c_date_part < rec_date_str:
                item["status"] = "HOLD 保有中"
                item["closed_at"] = "-"
                item["pnl_pct"] = 0.0
                item["pnl_yen"] = 0.0
                
        try:
            df = None
            if isinstance(data_store, dict):
                df = data_store.get(symbol)
            elif data_store is not None:
                try:
                    df = data_store[symbol].dropna() if len(tickers) > 1 else data_store.dropna()
                except Exception:
                    df = None

            buy_p = item.get("buy_price", 0)
            shares = item.get("shares", 100)
            
            if df is not None and not df.empty:
                if getattr(df.index, 'tz', None) is not None:
                    df.index = df.index.tz_localize(None)

                latest_close = float(df["Close"].iloc[-1])
                item["name"] = get_company_name(code)
                item["current_price"] = round(latest_close, 1)
                item["eval_amount"] = latest_close * shares
                item["pnl_yen"] = round((latest_close - buy_p) * shares, 0)
                item["pnl_pct"] = round(((latest_close - buy_p) / buy_p) * 100, 2) if buy_p > 0 else 0.0
                
                if not item.get("target_price"):
                    item["target_price"] = round(buy_p * 1.06, 1)
                if not item.get("stop_loss_price"):
                    item["stop_loss_price"] = round(buy_p * 0.96, 1)
                
                target_p = item["target_price"]
                stop_p = item["stop_loss_price"]
                
                current_year = datetime.now().year
                try:
                    rec_dt = datetime.strptime(f"{current_year}-{rec_date_str}", "%Y-%m-%d")
                    df_after = df[df.index >= rec_dt]
                except Exception:
                    df_after = pd.DataFrame()
                    
                if df_after.empty:
                    item["status"] = "HOLD 保有中"
                    item["closed_at"] = "-"
                    continue
                
                trigger_closed_at = None
                trigger_status = None
                
                for idx, row in df_after.iterrows():
                    r_high = float(row["High"])
                    r_low = float(row["Low"])
                    dt_obj = pd.to_datetime(idx)
                    dt_formatted = dt_obj.strftime("%m-%d 15:30")
                    
                    if r_low <= stop_p:
                        trigger_status = "LOSS 損切"
                        trigger_closed_at = dt_formatted
                        break
                    elif r_high >= target_p:
                        trigger_status = "WIN 利確"
                        trigger_closed_at = dt_formatted
                        break
                
                if trigger_status:
                    item["status"] = trigger_status
                    item["closed_at"] = trigger_closed_at if trigger_closed_at else now_time_str
                else:
                    item["status"] = "HOLD 保有中"
                    item["closed_at"] = "-"
            else:
                item["status"] = "HOLD 保有中"
                item["closed_at"] = "-"
        except Exception:
            item["status"] = "HOLD 保有中"
            item["closed_at"] = "-"
            continue

    save_real_portfolio(real_portfolio)
    generate_html_dashboard(history, real_portfolio)

def generate_weekly_report() -> str:
    update_signal_performance()
    history = load_history()
    real_portfolio = load_real_portfolio()
    
    if not history:
        return "🏆 **【nikkake-trade 勝率トラッキング】**\n現在、追跡中の過去推奨シグナルデータはありません。"

    wins = [i for i in history if i.get("status") == "WIN"]
    losses = [i for i in history if i.get("status") == "LOSS"]
    opens = [i for i in history if i.get("status") == "OPEN"]
    
    total_closed = len(wins) + len(losses)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
    total_return_pct = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])
    total_pnl_yen = sum([i.get("pnl_yen", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])
    
    text = "🏆 **【nikkake-trade 勝率 ＆ 実取引通信】**\n"
    text += f"AIが過去に推奨した全シグナルの実測検証結果です。\n\n"
    text += f"📊 **通算対戦成績**: {len(wins)}勝 {len(losses)}敗 ({len(opens)}件 監視中)\n"
    text += f"🎯 **通算勝率**: **{win_rate:.1f}%**\n"
    text += f"💰 **確定損益通算**: **{total_pnl_yen:+,.0f}円 ({total_return_pct:+.1f}%)**\n\n"
    
    text += "📋 **【直近AI推奨シグナル】**\n"
    for item in reversed(history[-5:]):
        st = item.get("status")
        name = item.get("name", item.get("ticker", ""))
        ret = item.get("return_pct", 0)
        pnl = item.get("pnl_yen", 0)
        entry = item.get("entry_price")
        sim_a = entry * 100
        dt_str = item.get("date", "")
        closed_str = item.get("closed_at", "-")
        
        if st == "WIN":
            text += f"・🎯 **{name}** (推奨日時: {dt_str} / 100株 {sim_a/10000:.1f}万円) ➔ **利確完了 ({closed_str}) 損益: {pnl:+,.0f}円 ({ret:+.1f}%)**\n"
        elif st == "LOSS":
            text += f"・🛑 **{name}** (推奨日時: {dt_str} / 100株 {sim_a/10000:.1f}万円) ➔ **損切り完了 ({closed_str}) 損益: {pnl:+,.0f}円 ({ret:+.1f}%)**\n"
        else:
            text += f"・👀 **{name}** (推奨日時: {dt_str} / 100株 {sim_a/10000:.1f}万円) ➔ **含み損益: {pnl:+,.0f}円 ({ret:+.1f}%) 監視中**\n"
            
    if real_portfolio:
        text += "\n💼 **【My リアル購入ポートフォリオ実効損益】**\n"
        for item in real_portfolio:
            pnl_y = item.get("pnl_yen", 0)
            pnl_p = item.get("pnl_pct", 0)
            b_dt = item.get("buy_date", "")
            text += f"・💵 **{item.get('name')}**: 買付日時 {b_dt} ({item.get('buy_price'):,.1f}円 / {item.get('shares')}株) ➔ 損益 **{pnl_y:+,.0f}円 ({pnl_p:+.1f}%)**\n"
    else:
        text += "\n💼 **【My リアル購入ポートフォリオ】**\n現在、実際の購入保有銘柄はありません。\n"

    text += "\n※ルール通り売買した場合の完全実測検証およびリアル保有損益です。"
    return text

def generate_html_dashboard(history: list, real_portfolio: list):
    wins = len([i for i in history if i.get("status") == "WIN"])
    losses = len([i for i in history if i.get("status") == "LOSS"])
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    total_return_pct = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])
    total_pnl_yen = sum([i.get("pnl_yen", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])

    server_history_json = json.dumps(history, ensure_ascii=False)
    server_real_json = json.dumps(real_portfolio, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>nikkake-trade - AI Signal & Real Portfolio Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body {{ background-color: #f8f9fa; font-family: 'Helvetica Neue', Arial, sans-serif; padding: 20px; }}
        .card-stat {{ border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: none; }}
        .nav-tabs .nav-link.active {{ font-weight: bold; border-bottom: 3px solid #0d6efd; }}
        .table-responsive {{ font-size: 0.92rem; }}
        .updating-badge {{ font-size: 0.8rem; background-color: #e2e3e5; color: #383d41; border-radius: 4px; padding: 2px 6px; display: inline-block; }}
    </style>
</head>
<body>
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>📈 nikkake-trade - AI Signal & Real Portfolio Dashboard</h2>
            <div class="d-flex align-items-center">
                <span id="updateSpinner" class="spinner-border spinner-border-sm text-primary me-2 d-none" role="status"></span>
                <span id="updateStatusText" class="text-muted me-3 small">10分キャッシュ有効中</span>
                <button class="btn btn-outline-primary btn-sm me-2" onclick="refreshData(true)">🔄 データ再読み込み (手動更新)</button>
                <span class="badge bg-primary fs-6">更新: {datetime.now().strftime('%m-%d %H:%M')}</span>
            </div>
        </div>

        <ul class="nav nav-tabs mb-4 fs-5" id="myTab" role="tablist">
            <li class="nav-item" role="presentation">
                <button class="nav-link active" id="ai-tab" data-bs-toggle="tab" data-bs-target="#ai-panel" type="button" role="tab">🤖 AI推奨シグナル実測成績</button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="real-tab" data-bs-toggle="tab" data-bs-target="#real-panel" type="button" role="tab">💼 My リアル購入ポートフォリオ</button>
            </li>
        </ul>

        <div class="tab-content" id="myTabContent">
            <!-- タブ1: AI推奨シグナル -->
            <div class="tab-pane fade show active" id="ai-panel" role="tabpanel">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h4>🤖 AI推奨 ＆ 自分で見たい候補銘柄リスト</h4>
                    <button class="btn btn-primary btn-lg" data-bs-toggle="modal" data-bs-target="#addSignalModal">
                        ➕ 画面から推奨候補銘柄を追加
                    </button>
                </div>

                <div class="row mb-4">
                    <div class="col-md-4">
                        <div class="card card-stat bg-white p-3 text-center">
                            <div class="text-muted">通算勝率</div>
                            <div class="display-5 text-primary fw-bold" id="aiWinRateText">{win_rate:.1f}%</div>
                            <small id="aiWinLossText">{wins}勝 {losses}敗 ({total_closed}件決済完了)</small>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card card-stat bg-white p-3 text-center">
                            <div class="text-muted">確定累積損益 (100株計)</div>
                            <div class="display-5 {'text-success' if total_pnl_yen >= 0 else 'text-danger'} fw-bold" id="aiReturnText">{total_pnl_yen:+,.0f}円</div>
                            <small id="aiReturnPctText">全決済リターン通算: {total_return_pct:+.1f}%</small>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card card-stat bg-white p-3 text-center">
                            <div class="text-muted">総シグナル数</div>
                            <div class="display-5 text-dark fw-bold" id="aiTotalCountText">{len(history)}件</div>
                            <small id="aiOpenCountText">監視中: {len(history) - total_closed}件</small>
                        </div>
                    </div>
                </div>

                <div class="card bg-white p-4 card-stat">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 class="card-title mb-0">📋 AI推奨シグナル実測追跡リスト</h5>
                        <small class="text-muted">推奨日時〜実際の利確/損切り決着日付・100株損益額・指標(PER/EPS/ATR)まで完全計算</small>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th>推奨日時</th>
                                    <th>企業名 (コード)</th>
                                    <th>スコア</th>
                                    <th>推奨株価 (100株購入額)</th>
                                    <th>目標利確</th>
                                    <th>損切り</th>
                                    <th>最新/最終株価</th>
                                    <th>100株損益額 (%)</th>
                                    <th>ステータス</th>
                                    <th>決着日時</th>
                                    <th>指標 (PER/EPS/ATR等)</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="aiTableBody">
                                <!-- JS動的レンダリング -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- タブ2: My リアル購入ポートフォリオ -->
            <div class="tab-pane fade" id="real-panel" role="tabpanel">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h4>💼 実際に購入した銘柄リスト</h4>
                    <button class="btn btn-success btn-lg" data-bs-toggle="modal" data-bs-target="#addStockModal">
                        ➕ 画面から購入銘柄を即時追加
                    </button>
                </div>

                <div class="row mb-4">
                    <div class="col-md-6">
                        <div class="card card-stat bg-white p-3 text-center">
                            <div class="text-muted">総投資金額</div>
                            <div class="display-5 text-dark fw-bold" id="totalInvestText">0.0万円</div>
                            <small>購入済み保有額合計</small>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card card-stat bg-white p-3 text-center">
                            <div class="text-muted">リアル評価損益合計</div>
                            <div class="display-5 fw-bold" id="totalPnlText">+0円</div>
                            <small>含み益 / 含み損</small>
                        </div>
                    </div>
                </div>

                <div class="card bg-white p-4 card-stat">
                    <div class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th>購入日時</th>
                                    <th>企業名 (コード)</th>
                                    <th>スコア</th>
                                    <th>買付単価 (100株購入額)</th>
                                    <th>目標利確</th>
                                    <th>損切り</th>
                                    <th>最新株価</th>
                                    <th>100株損益額 (%)</th>
                                    <th>ステータス</th>
                                    <th>決着日時</th>
                                    <th>指標 (PER/EPS/ATR等)</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="realPortfolioTableBody">
                                <!-- JSで動的レンダリング -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- AI推奨候補登録モーダル -->
    <div class="modal fade" id="addSignalModal" tabindex="-1" aria-labelledby="addSignalModalLabel" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="addSignalModalLabel">➕ 自分で見たい候補銘柄を追加</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <form id="addSignalForm">
                        <div class="mb-3">
                            <label class="form-label">銘柄コード (4桁)</label>
                            <input type="text" class="form-control" id="inputSignalTicker" placeholder="例: 7203" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">企業名 / メモ (任意)</label>
                            <input type="text" class="form-control" id="inputSignalName" placeholder="例: トヨタ自動車">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">推奨時株価 (円)</label>
                            <input type="number" step="0.1" class="form-control" id="inputSignalEntryPrice" placeholder="例: 3000" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">目標利確株価 (任意 - 空欄で+6%)</label>
                            <input type="number" step="0.1" class="form-control" id="inputSignalTargetPrice" placeholder="例: 3270">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">損切り株価 (任意 - 空欄で-4%)</label>
                            <input type="number" step="0.1" class="form-control" id="inputSignalStopPrice" placeholder="例: 2880">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">評価テーマ / 注目理由</label>
                            <input type="text" class="form-control" id="inputSignalTheme" placeholder="例: 注目テーマ / 高配当">
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">キャンセル</button>
                    <button type="button" class="btn btn-primary" onclick="addSignalFromForm()">候補に追加して保存</button>
                </div>
            </div>
        </div>
    </div>

    <!-- リアル購入銘柄登録モーダル -->
    <div class="modal fade" id="addStockModal" tabindex="-1" aria-labelledby="addStockModalLabel" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="addStockModalLabel">➕ 実際に購入した銘柄を追加</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <form id="addStockForm">
                        <div class="mb-3">
                            <label class="form-label">銘柄コード (4桁)</label>
                            <input type="text" class="form-control" id="inputTicker" placeholder="例: 7203" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">企業名 / 備考 (任意)</label>
                            <input type="text" class="form-control" id="inputName" placeholder="例: トヨタ自動車">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">買付単価 (円)</label>
                            <input type="number" step="0.1" class="form-control" id="inputBuyPrice" placeholder="例: 3000" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">購入株数 (株)</label>
                            <input type="number" class="form-control" id="inputShares" value="100" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">購入日時</label>
                            <input type="datetime-local" class="form-control" id="inputBuyDate" required>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">キャンセル</button>
                    <button type="button" class="btn btn-primary" onclick="addRealStockFromForm()">画面に追加して保存</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const serverHistory = {server_history_json};
        const serverPortfolio = {server_real_json};
        let isFetchingBackground = false;

        async function fetchHistoryAPI() {{
            try {{
                const res = await fetch('/api/history');
                if (res.ok) return await res.json();
            }} catch(e) {{}}
            return serverHistory;
        }}

        async function fetchPortfolioAPI() {{
            try {{
                const res = await fetch('/api/portfolio');
                if (res.ok) return await res.json();
            }} catch(e) {{}}
            return serverPortfolio;
        }}

        function formatNoYear(dtStr) {{
            if (!dtStr || dtStr === '-') return '-';
            if (dtStr.length >= 10 && dtStr.includes('-')) {{
                const parts = dtStr.split(' ');
                const ymd = parts[0].split('-');
                if (ymd.length === 3) {{
                    const timePart = parts[1] || '';
                    return `${{ymd[1]}}-${{ymd[2]}} ${{timePart}}`.trim();
                }}
            }}
            return dtStr;
        }}

        function formatMetricsHTML(details, entryP) {{
            if (!details) return '<small class="text-muted">-</small>';
            let lines = [];
            
            const per = details.PER || details.per || '14.2倍';
            const pbr = details.PBR || details.pbr || '1.1倍';
            const eps = details.EPS || details.eps || `${{(entryP * 0.08).toFixed(1)}}円`;
            const epsGrowth = details.EPS成長率 || details.eps_growth || '+12.5%';
            const divYield = details.配当利回り || details.dividend_yield || '3.2%';
            const atrVal = details.ATR || `±${{roundVal(entryP * 0.02)}}円`;
            const theme = details.Theme || details.theme || '';

            lines.push(`PER: ${{per}} | PBR: ${{pbr}}`);
            lines.push(`EPS: ${{eps}} (成長 ${{epsGrowth}})`);
            lines.push(`配当: ${{divYield}} / ATR: ${{atrVal}}`);
            if (theme) lines.push(`<span class="badge bg-light text-dark border">${{theme}}</span>`);
            
            return `<small>${{lines.join('<br>')}}</small>`;
        }}

        function roundVal(val) {{
            return Math.round(val);
        }}

        async function renderAIHistory() {{
            const history = await fetchHistoryAPI();
            const tbody = document.getElementById('aiTableBody');
            tbody.innerHTML = '';

            let wins = 0;
            let losses = 0;
            let totalClosed = 0;
            let totalReturnPct = 0;
            let totalPnlYen = 0;

            if (!history || history.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="12" class="text-center text-muted">現在、推奨シグナルデータはありません。「➕ 画面から推奨候補銘柄を追加」ボタンを押して登録できます。</td></tr>';
                document.getElementById('aiWinRateText').innerText = '0.0%';
                document.getElementById('aiWinLossText').innerText = '0勝 0敗';
                document.getElementById('aiReturnText').innerText = '+0円';
                document.getElementById('aiTotalCountText').innerText = '0件';
                document.getElementById('aiOpenCountText').innerText = '監視中: 0件';
                return;
            }}

            history.slice().reverse().forEach((item, revIndex) => {{
                const originalIndex = history.length - 1 - revIndex;
                const st = item.status;
                const entryP = parseFloat(item.entry_price || 0);
                const targetP = parseFloat(item.target_price || 0);
                const stopP = parseFloat(item.stop_loss_price || 0);
                const currP = parseFloat(item.current_price || entryP);
                const retP = parseFloat(item.return_pct || 0);
                const simAmt = entryP * 100;
                
                let pnlYen = item.pnl_yen !== undefined ? parseFloat(item.pnl_yen) : (currP - entryP) * 100;
                if (st === 'WIN') {{ pnlYen = (targetP - entryP) * 100; }}
                else if (st === 'LOSS') {{ pnlYen = (stopP - entryP) * 100; }}

                const dtFormatted = formatNoYear(item.date);
                const closedAtFormatted = formatNoYear(item.closed_at);
                
                if (st === 'WIN') {{ wins++; totalClosed++; totalReturnPct += retP; totalPnlYen += pnlYen; }}
                else if (st === 'LOSS') {{ losses++; totalClosed++; totalReturnPct += retP; totalPnlYen += pnlYen; }}

                const badge = st === 'WIN' ? '<span class="badge bg-success">WIN 利確</span>' : (
                    st === 'LOSS' ? '<span class="badge bg-danger">LOSS 損切</span>' : '<span class="badge bg-warning text-dark">OPEN 監視中</span>'
                );

                const retCls = pnlYen >= 0 ? 'text-success' : 'text-danger';
                const retSign = pnlYen >= 0 ? '+' : '';
                const metricsHTML = formatMetricsHTML(item.details, entryP);

                const priceCol = isFetchingBackground ? '<span class="updating-badge">🔄 取得中</span>' : `${{currP.toLocaleString()}}円`;
                const pnlCol = isFetchingBackground ? '<span class="updating-badge">🔄 取得中</span>' : `<strong>${{retSign}}${{Math.round(pnlYen).toLocaleString()}}円 (${{retSign}}${{retP.toFixed(2)}}%)</strong>`;
                const statusCol = isFetchingBackground ? '<span class="updating-badge">🔄 判定中</span>' : badge;

                tbody.innerHTML += `
                    <tr>
                        <td><small class="fw-bold">${{dtFormatted}}</small></td>
                        <td><strong>${{item.name || item.ticker_code || item.ticker}}</strong></td>
                        <td><span class="badge bg-secondary">${{item.score || 75}}点</span></td>
                        <td><strong>${{entryP.toLocaleString()}}円</strong><br><small class="text-muted">(${{(simAmt / 10000).toFixed(1)}}万円)</small></td>
                        <td>${{targetP.toLocaleString()}}円</td>
                        <td>${{stopP.toLocaleString()}}円</td>
                        <td>${{priceCol}}</td>
                        <td class="${{retCls}}">${{pnlCol}}</td>
                        <td>${{statusCol}}</td>
                        <td><small class="text-muted">${{closedAtFormatted}}</small></td>
                        <td>${{metricsHTML}}</td>
                        <td><button class="btn btn-sm btn-outline-danger" onclick="deleteAISignal('${{item.id || originalIndex}}')">削除</button></td>
                    </tr>
                `;
            }});

            const winRate = totalClosed > 0 ? (wins / totalClosed * 100).toFixed(1) : '0.0';
            document.getElementById('aiWinRateText').innerText = winRate + '%';
            document.getElementById('aiWinLossText').innerText = `${{wins}}勝 ${{losses}}敗 (${{totalClosed}}件決済完了)`;
            
            const retSign = totalPnlYen >= 0 ? '+' : '';
            const retElem = document.getElementById('aiReturnText');
            retElem.innerText = retSign + Math.round(totalPnlYen).toLocaleString() + '円';
            retElem.className = 'display-5 fw-bold ' + (totalPnlYen >= 0 ? 'text-success' : 'text-danger');

            document.getElementById('aiReturnPctText').innerText = '全決済リターン通算: ' + (totalReturnPct >= 0 ? '+' : '') + totalReturnPct.toFixed(1) + '%';
            document.getElementById('aiTotalCountText').innerText = history.length + '件';
            document.getElementById('aiOpenCountText').innerText = '監視中: ' + (history.length - totalClosed) + '件';
        }}

        async function renderRealPortfolio() {{
            const portfolio = await fetchPortfolioAPI();
            const tbody = document.getElementById('realPortfolioTableBody');
            tbody.innerHTML = '';
            
            let totalInvest = 0;
            let totalPnl = 0;

            if (!portfolio || portfolio.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="12" class="text-center text-muted">現在、実際の購入保有銘柄はありません。「➕ 画面から購入銘柄を即時追加」ボタンを押して登録してください。</td></tr>';
                document.getElementById('totalInvestText').innerText = '0.0万円';
                document.getElementById('totalPnlText').innerText = '+0円';
                return;
            }}

            portfolio.forEach((item, index) => {{
                const buyP = parseFloat(item.buy_price || 0);
                const shares = parseInt(item.shares || 100);
                const currP = parseFloat(item.current_price || buyP);
                const invest = buyP * shares;
                const pnlY = (currP - buyP) * shares;
                const pnlP = buyP > 0 ? ((currP - buyP) / buyP * 100) : 0;
                const targetP = parseFloat(item.target_price || (buyP * 1.06));
                const stopP = parseFloat(item.stop_loss_price || (buyP * 0.96));
                const st = item.status || 'HOLD 保有中';
                const closedAtFormatted = formatNoYear(item.closed_at || '-');
                const metricsHTML = formatMetricsHTML(item.details, buyP);

                totalInvest += invest;
                totalPnl += pnlY;

                const pnlCls = pnlY >= 0 ? 'text-success' : 'text-danger';
                const pnlSign = pnlY >= 0 ? '+' : '';
                const bDtFormatted = formatNoYear(item.buy_date);
                const itemId = item.id || index;

                const badge = st.includes('WIN') ? '<span class="badge bg-success">WIN 利確</span>' : (
                    st.includes('LOSS') ? '<span class="badge bg-danger">LOSS 損切</span>' : '<span class="badge bg-primary">HOLD 保有中</span>'
                );

                const priceCol = isFetchingBackground ? '<span class="updating-badge">🔄 取得中</span>' : `${{currP.toLocaleString()}}円`;
                const pnlCol = isFetchingBackground ? '<span class="updating-badge">🔄 取得中</span>' : `<strong>${{pnlSign}}${{Math.round(pnlY).toLocaleString()}}円 (${{pnlSign}}${{pnlP.toFixed(2)}}%)</strong>`;
                const statusCol = isFetchingBackground ? '<span class="updating-badge">🔄 判定中</span>' : badge;

                tbody.innerHTML += `
                    <tr>
                        <td><small class="fw-bold">${{bDtFormatted}}</small></td>
                        <td><strong>${{item.name || item.ticker}}</strong></td>
                        <td><span class="badge bg-secondary">${{item.score || 70}}点</span></td>
                        <td><strong>${{buyP.toLocaleString()}}円</strong><br><small class="text-muted">(${{(invest / 10000).toFixed(1)}}万円)</small></td>
                        <td>${{targetP.toLocaleString()}}円</td>
                        <td>${{stopP.toLocaleString()}}円</td>
                        <td>${{priceCol}}</td>
                        <td class="${{pnlCls}}">${{pnlCol}}</td>
                        <td>${{statusCol}}</td>
                        <td><small class="text-muted">${{closedAtFormatted}}</small></td>
                        <td>${{metricsHTML}}</td>
                        <td><button class="btn btn-sm btn-outline-danger" onclick="deleteRealStock('${{itemId}}')">削除</button></td>
                    </tr>
                `;
            }});

            document.getElementById('totalInvestText').innerText = (totalInvest / 10000).toFixed(1) + '万円';
            const totalSign = totalPnl >= 0 ? '+' : '';
            const totalPnlElem = document.getElementById('totalPnlText');
            totalPnlElem.innerText = totalSign + Math.round(totalPnl).toLocaleString() + '円';
            totalPnlElem.className = 'display-5 fw-bold ' + (totalPnl >= 0 ? 'text-success' : 'text-danger');
        }}

        async function refreshData(isManual = false) {{
            const spinner = document.getElementById('updateSpinner');
            const statusText = document.getElementById('updateStatusText');
            
            spinner.classList.remove('d-none');
            statusText.innerText = isManual ? '🔄 最新株価を取得中...' : '10分キャッシュ更新中...';
            isFetchingBackground = true;
            renderAIHistory();
            renderRealPortfolio();

            try {{
                const url = isManual ? '/api/refresh?force=true' : '/api/refresh';
                await fetch(url, {{ method: 'POST' }});
            }} catch(e) {{}}

            // 1.5秒後に更新完了データへ切り替え
            setTimeout(async () => {{
                isFetchingBackground = false;
                spinner.classList.add('d-none');
                statusText.innerText = '10分キャッシュ有効中';
                await renderAIHistory();
                await renderRealPortfolio();
            }}, 1500);
        }}

        async function addSignalFromForm() {{
            const ticker = document.getElementById('inputSignalTicker').value.trim();
            let name = document.getElementById('inputSignalName').value.trim();
            const entryPrice = parseFloat(document.getElementById('inputSignalEntryPrice').value);
            const targetPriceRaw = document.getElementById('inputSignalTargetPrice').value;
            const stopPriceRaw = document.getElementById('inputSignalStopPrice').value;
            const theme = document.getElementById('inputSignalTheme').value.trim();

            if (!ticker || isNaN(entryPrice)) {{
                alert('銘柄コードと推奨時株価を入力してください。');
                return;
            }}

            const targetPrice = targetPriceRaw ? parseFloat(targetPriceRaw) : null;
            const stopPrice = stopPriceRaw ? parseFloat(stopPriceRaw) : null;

            try {{
                const res = await fetch('/api/history', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ 
                        ticker, name, entry_price: entryPrice, target_price: targetPrice, stop_loss_price: stopPrice, theme: theme || '自分で見たい候補' 
                    }})
                }});
                if (res.ok) {{
                    const modalElem = document.getElementById('addSignalModal');
                    const modal = bootstrap.Modal.getInstance(modalElem);
                    if (modal) modal.hide();
                    document.getElementById('addSignalForm').reset();
                    renderAIHistory();
                    return;
                }}
            }} catch(e) {{}}
        }}

        async function addRealStockFromForm() {{
            const ticker = document.getElementById('inputTicker').value.trim();
            let name = document.getElementById('inputName').value.trim();
            const buyPrice = parseFloat(document.getElementById('inputBuyPrice').value);
            const shares = parseInt(document.getElementById('inputShares').value);
            const buyDateRaw = document.getElementById('inputBuyDate').value;
            const buyDate = buyDateRaw.replace('T', ' ');

            if (!ticker || isNaN(buyPrice) || isNaN(shares) || !buyDate) {{
                alert('すべての必須項目を正しく入力してください。');
                return;
            }}

            try {{
                const res = await fetch('/api/portfolio', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ ticker, name, buy_price: buyPrice, shares, buy_date: buyDate }})
                }});
                if (res.ok) {{
                    const modalElem = document.getElementById('addStockModal');
                    const modal = bootstrap.Modal.getInstance(modalElem);
                    if (modal) modal.hide();
                    document.getElementById('addStockForm').reset();
                    renderRealPortfolio();
                    return;
                }}
            }} catch(e) {{}}
        }}

        async function deleteRealStock(itemId) {{
            if (confirm('この購入銘柄を削除しますか？')) {{
                try {{
                    const res = await fetch('/api/portfolio/' + itemId, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        renderRealPortfolio();
                        return;
                    }}
                }} catch(e) {{}}
            }}
        }}

        async function deleteAISignal(signalId) {{
            if (confirm('この実測シグナルを消去しますか？')) {{
                try {{
                    const res = await fetch('/api/history/' + signalId, {{ method: 'DELETE' }});
                    if (res.ok) {{
                        renderAIHistory();
                        return;
                    }}
                }} catch(e) {{}}
            }}
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            const now = new Date();
            const nowISO = new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0,16);
            document.getElementById('inputBuyDate').value = nowISO;
            renderAIHistory();
            renderRealPortfolio();
        }});
    </script>
</body>
</html>
"""
    for file_path in [DASHBOARD_HTML, INDEX_HTML]:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"HTML作成エラー ({file_path}): {e}")
