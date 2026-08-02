import json
import os
import time
from datetime import datetime
import yfinance as yf
import pandas as pd

HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "signal_history.json")
DASHBOARD_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html")

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

def record_signal(ticker: str, entry_price: float, target_price: float, stop_loss_price: float, score: int, details: dict):
    """
    AIが推奨を出したシグナルを自動記録
    """
    history = load_history()
    
    # 既に同じ日に同じ銘柄が記録されていれば重複を防止
    today_str = datetime.now().strftime("%Y-%m-%d")
    for item in history:
        if item.get("ticker") == ticker and item.get("date") == today_str:
            return
            
    signal_entry = {
        "id": f"{ticker}_{today_str}",
        "date": today_str,
        "ticker": ticker.replace('.T', ''),
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "score": score,
        "status": "OPEN", # OPEN, WIN, LOSS
        "current_price": entry_price,
        "max_price": entry_price,
        "min_price": entry_price,
        "return_pct": 0.0,
        "details": details
    }
    history.append(signal_entry)
    save_history(history)

def update_signal_performance():
    """
    オープン中の全シグナルの最新株価を取得し、勝敗判定を行う
    """
    history = load_history()
    if not history:
        return

    open_signals = [item for item in history if item.get("status") == "OPEN"]
    if not open_signals:
        return

    tickers = list(set([item["ticker"] + ".T" for item in open_signals]))
    try:
        data = yf.download(tickers, period="1mo", group_by="ticker", progress=False)
    except Exception as e:
        print(f"勝敗追跡データ取得エラー: {e}")
        return

    updated = False
    for item in history:
        if item.get("status") != "OPEN":
            continue
            
        symbol = item["ticker"] + ".T"
        try:
            df = data[symbol].dropna() if len(tickers) > 1 else data.dropna()
            if df.empty:
                continue

            entry_p = item["entry_price"]
            target_p = item["target_price"]
            stop_p = item["stop_loss_price"]
            
            # 推奨日以降のデータを検証
            signal_date = item["date"]
            df_after = df[df.index >= signal_date]
            if df_after.empty:
                df_after = df
                
            high_price = float(df_after["High"].max())
            low_price = float(df_after["Low"].min())
            latest_close = float(df_after["Close"].iloc[-1])
            
            item["current_price"] = latest_close
            item["max_price"] = max(item.get("max_price", entry_p), high_price)
            item["min_price"] = min(item.get("min_price", entry_p), low_price)
            item["return_pct"] = round(((latest_close - entry_p) / entry_p) * 100, 2)
            
            # 勝敗判定: 目標株価到達なら WIN / 損切りライン到達なら LOSS
            if high_price >= target_p:
                item["status"] = "WIN"
                item["return_pct"] = round(((target_p - entry_p) / entry_p) * 100, 2)
                item["close_date"] = datetime.now().strftime("%Y-%m-%d")
                updated = True
            elif low_price <= stop_p:
                item["status"] = "LOSS"
                item["return_pct"] = round(((stop_p - entry_p) / entry_p) * 100, 2)
                item["close_date"] = datetime.now().strftime("%Y-%m-%d")
                updated = True
            else:
                updated = True
        except Exception:
            continue

    if updated:
        save_history(history)
        generate_html_dashboard(history)

def generate_weekly_report() -> str:
    """
    LINE送信用の週次勝率・通算成績サマリーを生成
    """
    update_signal_performance()
    history = load_history()
    
    if not history:
        return "🏆 **【AIトレード勝率トラッキング】**\n現在、追跡中の過去推奨シグナルデータはありません。"

    wins = [i for i in history if i.get("status") == "WIN"]
    losses = [i for i in history if i.get("status") == "LOSS"]
    opens = [i for i in history if i.get("status") == "OPEN"]
    
    total_closed = len(wins) + len(losses)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
    
    total_return = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])
    
    text = "🏆 **【AIトレード勝率・成績トラッキング通信】**\n"
    text += f"AIが過去に推奨した全シグナルの追跡検証結果です。\n\n"
    text += f"📊 **通算対戦成績**: {len(wins)}勝 {len(losses)}敗 ({len(opens)}件 監視中)\n"
    text += f"🎯 **通算勝率**: **{win_rate:.1f}%**\n"
    text += f"💰 **確定通算リターン**: **{total_return:+.1f}%**\n\n"
    
    text += "📋 **【直近推奨銘柄のフォローステータス】**\n"
    for item in reversed(history[-5:]):
        st = item.get("status")
        sym = item.get("ticker")
        ret = item.get("return_pct", 0)
        entry = item.get("entry_price")
        curr = item.get("current_price")
        
        if st == "WIN":
            text += f"・🎯 **{sym}** (推奨: {entry:.1f}円) ➔ **利確達成 🎉 ({ret:+.1f}%)**\n"
        elif st == "LOSS":
            text += f"・🛑 **{sym}** (推奨: {entry:.1f}円) ➔ **損切り撤退 🛑 ({ret:+.1f}%)**\n"
        else:
            text += f"・👀 **{sym}** (推奨: {entry:.1f}円 ➔ 現在: {curr:.1f}円 / {ret:+.1f}% 監視中)\n"
            
    text += "\n※ルール通り利確・損切りを実行した場合の完全実測検証結果です。"
    return text

def generate_html_dashboard(history: list):
    """
    ブラウザでビジュアル確認できる dashboard.html を自動更新
    """
    wins = len([i for i in history if i.get("status") == "WIN"])
    losses = len([i for i in history if i.get("status") == "LOSS"])
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    total_return = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])

    rows_html = ""
    for item in reversed(history):
        st = item.get("status")
        badge = '<span class="badge bg-success">WIN 利確</span>' if st == "WIN" else (
            '<span class="badge bg-danger">LOSS 損切</span>' if st == "LOSS" else '<span class="badge bg-warning">OPEN 監視中</span>'
        )
        rows_html += f"""
        <tr>
            <td>{item.get('date')}</td>
            <td><strong>{item.get('ticker')}</strong></td>
            <td>{item.get('score')}点</td>
            <td>{item.get('entry_price'):,.1f}円</td>
            <td>{item.get('target_price'):,.1f}円</td>
            <td>{item.get('stop_loss_price'):,.1f}円</td>
            <td>{item.get('current_price'):,.1f}円</td>
            <td><strong>{item.get('return_pct'):+.2f}%</strong></td>
            <td>{badge}</td>
        </tr>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>AI Trade Signal Performance Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background-color: #f8f9fa; font-family: sans-serif; padding: 20px; }}
        .card-stat {{ border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
    </style>
</head>
<body>
    <div class="container">
        <h2 class="mb-4">🤖 AI Trade Signal Performance Dashboard</h2>
        <div class="row mb-4">
            <div class="col-md-4">
                <div class="card card-stat bg-white p-3 text-center">
                    <div class="text-muted">通算勝率</div>
                    <div class="display-5 text-primary font-weight-bold">{win_rate:.1f}%</div>
                    <small>{wins}勝 {losses}敗</small>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-stat bg-white p-3 text-center">
                    <div class="text-muted">確定累積リターン</div>
                    <div class="display-5 {'text-success' if total_return >= 0 else 'text-danger'}">{total_return:+.1f}%</div>
                    <small>全利確・損切り決済合計</small>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-stat bg-white p-3 text-center">
                    <div class="text-muted">総シグナル数</div>
                    <div class="display-5 text-dark">{len(history)}件</div>
                    <small>監視中: {len(history) - total_closed}件</small>
                </div>
            </div>
        </div>

        <div class="card bg-white p-4 card-stat">
            <h5>📋 シグナル勝敗・実測追跡履歴</h5>
            <table class="table table-hover mt-3">
                <thead class="table-light">
                    <tr>
                        <th>推奨日</th>
                        <th>銘柄</th>
                        <th>スコア</th>
                        <th>推奨価格</th>
                        <th>目標利確</th>
                        <th>損切り</th>
                        <th>最新/最終株価</th>
                        <th>リターン</th>
                        <th>ステータス</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""
    try:
        with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"HTMLダッシュボード作成エラー: {e}")
