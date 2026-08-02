import json
import os
import time
from datetime import datetime
import yfinance as yf
import pandas as pd
from common.stock_names import get_company_name

HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "signal_history.json")
REAL_PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "real_portfolio.json")
DASHBOARD_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html")
INDEX_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")

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
    today_str = datetime.now().strftime("%Y-%m-%d")
    code = ticker.replace('.T', '').strip()
    
    for item in history:
        if item.get("ticker_code") == code and item.get("date") == today_str:
            return
            
    name = get_company_name(code)
    sim_amount = entry_price * 100
    
    signal_entry = {
        "id": f"{code}_{today_str}",
        "date": today_str,
        "ticker_code": code,
        "name": name,
        "entry_price": entry_price,
        "sim_amount": sim_amount,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "score": score,
        "status": "OPEN",
        "current_price": entry_price,
        "max_price": entry_price,
        "min_price": entry_price,
        "return_pct": 0.0,
        "details": details
    }
    history.append(signal_entry)
    save_history(history)

def update_signal_performance():
    history = load_history()
    real_portfolio = load_real_portfolio()
    
    all_tickers = []
    if history:
        all_tickers.extend([item.get("ticker_code", item.get("ticker", "")) + ".T" for item in history if item.get("status") == "OPEN"])
    if real_portfolio:
        all_tickers.extend([item.get("ticker", "") + ".T" for item in real_portfolio])
        
    tickers = list(set([t for t in all_tickers if t != ".T"]))
    if not tickers:
        generate_html_dashboard(history, real_portfolio)
        return

    try:
        data = yf.download(tickers, period="1mo", group_by="ticker", progress=False)
    except Exception as e:
        print(f"株追跡データ取得エラー: {e}")
        generate_html_dashboard(history, real_portfolio)
        return

    for item in history:
        if item.get("status") != "OPEN":
            continue
            
        code = item.get("ticker_code", item.get("ticker", ""))
        symbol = code + ".T"
        try:
            df = data[symbol].dropna() if len(tickers) > 1 else data.dropna()
            if df.empty:
                continue

            entry_p = item["entry_price"]
            target_p = item["target_price"]
            stop_p = item["stop_loss_price"]
            
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
            
            if high_price >= target_p:
                item["status"] = "WIN"
                item["return_pct"] = round(((target_p - entry_p) / entry_p) * 100, 2)
                item["close_date"] = datetime.now().strftime("%Y-%m-%d")
            elif low_price <= stop_p:
                item["status"] = "LOSS"
                item["return_pct"] = round(((stop_p - entry_p) / entry_p) * 100, 2)
                item["close_date"] = datetime.now().strftime("%Y-%m-%d")
        except Exception:
            continue

    save_history(history)

    for item in real_portfolio:
        code = item.get("ticker", "")
        symbol = code + ".T"
        try:
            df = data[symbol].dropna() if len(tickers) > 1 else data.dropna()
            if not df.empty:
                latest_close = float(df["Close"].iloc[-1])
                buy_p = item.get("buy_price", 0)
                shares = item.get("shares", 100)
                
                item["name"] = get_company_name(code)
                item["current_price"] = latest_close
                item["eval_amount"] = latest_close * shares
                item["pnl_yen"] = (latest_close - buy_p) * shares
                item["pnl_pct"] = round(((latest_close - buy_p) / buy_p) * 100, 2) if buy_p > 0 else 0.0
        except Exception:
            continue

    save_real_portfolio(real_portfolio)
    generate_html_dashboard(history, real_portfolio)

def generate_weekly_report() -> str:
    update_signal_performance()
    history = load_history()
    real_portfolio = load_real_portfolio()
    
    if not history:
        return "🏆 **【AIトレード勝率トラッキング】**\n現在、追跡中の過去推奨シグナルデータはありません。"

    wins = [i for i in history if i.get("status") == "WIN"]
    losses = [i for i in history if i.get("status") == "LOSS"]
    opens = [i for i in history if i.get("status") == "OPEN"]
    
    total_closed = len(wins) + len(losses)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
    total_return = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])
    
    text = "🏆 **【AIトレード勝率 ＆ 実取引パフォーマンス通信】**\n"
    text += f"AIが過去に推奨した全シグナルの実測検証結果です。\n\n"
    text += f"📊 **通算対戦成績**: {len(wins)}勝 {len(losses)}敗 ({len(opens)}件 監視中)\n"
    text += f"🎯 **通算勝率**: **{win_rate:.1f}%**\n"
    text += f"💰 **確定通算リターン**: **{total_return:+.1f}%**\n\n"
    
    text += "📋 **【直近AI推奨シグナル】**\n"
    for item in reversed(history[-5:]):
        st = item.get("status")
        name = item.get("name", item.get("ticker", ""))
        ret = item.get("return_pct", 0)
        entry = item.get("entry_price")
        sim_a = entry * 100
        
        if st == "WIN":
            text += f"・🎯 **{name}** (推奨: {entry:,.1f}円 / 100株 {sim_a/10000:.1f}万円) ➔ **利確達成 🎉 ({ret:+.1f}%)**\n"
        elif st == "LOSS":
            text += f"・🛑 **{name}** (推奨: {entry:,.1f}円 / 100株 {sim_a/10000:.1f}万円) ➔ **損切り撤退 🛑 ({ret:+.1f}%)**\n"
        else:
            text += f"・👀 **{name}** (推奨: {entry:,.1f}円 / 100株 {sim_a/10000:.1f}万円 / {ret:+.1f}% 監視中)\n"
            
    if real_portfolio:
        text += "\n💼 **【My リアル購入ポートフォリオ実効損益】**\n"
        for item in real_portfolio:
            pnl_y = item.get("pnl_yen", 0)
            pnl_p = item.get("pnl_pct", 0)
            text += f"・💵 **{item.get('name')}**: 買付 {item.get('buy_price'):,.1f}円({item.get('shares')}株) ➔ 損益 **{pnl_y:+,.0f}円 ({pnl_p:+.1f}%)**\n"
    else:
        text += "\n💼 **【My リアル購入ポートフォリオ】**\n現在、実際の購入保有銘柄はありません（画面から追加可能）。\n"

    text += "\n※ルール通り売買した場合の完全実測検証およびリアル保有損益です。"
    return text

def generate_html_dashboard(history: list, real_portfolio: list):
    wins = len([i for i in history if i.get("status") == "WIN"])
    losses = len([i for i in history if i.get("status") == "LOSS"])
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    total_return = sum([i.get("return_pct", 0) for i in history if i.get("status") in ["WIN", "LOSS"]])

    server_history_json = json.dumps(history, ensure_ascii=False)
    server_real_json = json.dumps(real_portfolio, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>trade - AI Signal & Real Portfolio Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body {{ background-color: #f8f9fa; font-family: 'Helvetica Neue', Arial, sans-serif; padding: 20px; }}
        .card-stat {{ border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: none; }}
        .nav-tabs .nav-link.active {{ font-weight: bold; border-bottom: 3px solid #0d6efd; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>🤖 trade - AI Signal & Real Portfolio Dashboard</h2>
            <span class="badge bg-primary fs-6">更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
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
                            <div class="text-muted">確定累積リターン</div>
                            <div class="display-5 {'text-success' if total_return >= 0 else 'text-danger'} fw-bold" id="aiReturnText">{total_return:+.1f}%</div>
                            <small>全決済シグナル合計</small>
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
                        <small class="text-muted">不要なシミュレーションシグナルは右端の「削除」ボタンで消去可能</small>
                    </div>
                    <div class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead class="table-light">
                                <tr>
                                    <th>推奨日</th>
                                    <th>企業名 (コード)</th>
                                    <th>スコア</th>
                                    <th>推奨株価</th>
                                    <th>100株シミュレーション</th>
                                    <th>目標利確</th>
                                    <th>損切り</th>
                                    <th>最新/最終株価</th>
                                    <th>リターン</th>
                                    <th>ステータス</th>
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
                    <div>
                        <button class="btn btn-outline-secondary me-2" onclick="copyPortfolioJSON()">📋 登録データをAIへ同期用にコピー</button>
                        <button class="btn btn-success btn-lg" data-bs-toggle="modal" data-bs-target="#addStockModal">
                            ➕ 画面から購入銘柄を即時追加
                        </button>
                    </div>
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
                                    <th>購入日</th>
                                    <th>銘柄コード/企業名</th>
                                    <th>買付単価</th>
                                    <th>保有株数</th>
                                    <th>投資金額</th>
                                    <th>現在株価</th>
                                    <th>評価損益 (円/%)</th>
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

    <!-- 銘柄登録モーダル -->
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
                            <label class="form-label">購入日</label>
                            <input type="date" class="form-control" id="inputBuyDate" required>
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
        
        function getLocalHistory() {{
            const stored = localStorage.getItem('user_ai_history');
            if (stored) {{
                try {{ return JSON.parse(stored); }} catch(e) {{}}
            }}
            return serverHistory;
        }}

        function saveLocalHistory(data) {{
            localStorage.setItem('user_ai_history', JSON.stringify(data));
            renderAIHistory();
        }}
        
        function getLocalPortfolio() {{
            const stored = localStorage.getItem('user_real_portfolio');
            if (stored) {{
                try {{ return JSON.parse(stored); }} catch(e) {{}}
            }}
            return serverPortfolio;
        }}
        
        function saveLocalPortfolio(data) {{
            localStorage.setItem('user_real_portfolio', JSON.stringify(data));
            renderRealPortfolio();
        }}

        function renderAIHistory() {{
            const history = getLocalHistory();
            const tbody = document.getElementById('aiTableBody');
            tbody.innerHTML = '';

            let wins = 0;
            let losses = 0;
            let totalClosed = 0;
            let totalReturn = 0;

            if (!history || history.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">現在、実測推奨シグナルデータはありません。</td></tr>';
                document.getElementById('aiWinRateText').innerText = '0.0%';
                document.getElementById('aiWinLossText').innerText = '0勝 0敗';
                document.getElementById('aiReturnText').innerText = '+0.0%';
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
                
                if (st === 'WIN') {{ wins++; totalClosed++; totalReturn += retP; }}
                else if (st === 'LOSS') {{ losses++; totalClosed++; totalReturn += retP; }}

                const badge = st === 'WIN' ? '<span class="badge bg-success">WIN 利確</span>' : (
                    st === 'LOSS' ? '<span class="badge bg-danger">LOSS 損切</span>' : '<span class="badge bg-warning text-dark">OPEN 監視中</span>'
                );

                const retCls = retP >= 0 ? 'text-success' : 'text-danger';
                const retSign = retP >= 0 ? '+' : '';

                tbody.innerHTML += `
                    <tr>
                        <td>${{item.date || '-'}}</td>
                        <td><strong>${{item.name || item.ticker_code || item.ticker}}</strong></td>
                        <td><span class="badge bg-secondary">${{item.score || 60}}点</span></td>
                        <td>${{entryP.toLocaleString()}}円</td>
                        <td>${{(simAmt / 10000).toFixed(1)}}万円</td>
                        <td>${{targetP.toLocaleString()}}円</td>
                        <td>${{stopP.toLocaleString()}}円</td>
                        <td>${{currP.toLocaleString()}}円</td>
                        <td class="${{retCls}}"><strong>${{retSign}}${{retP.toFixed(2)}}%</strong></td>
                        <td>${{badge}}</td>
                        <td><button class="btn btn-sm btn-outline-danger" onclick="deleteAISignal(${{originalIndex}})">削除</button></td>
                    </tr>
                `;
            }});

            const winRate = totalClosed > 0 ? (wins / totalClosed * 100).toFixed(1) : '0.0';
            document.getElementById('aiWinRateText').innerText = winRate + '%';
            document.getElementById('aiWinLossText').innerText = `${{wins}}勝 ${{losses}}敗 (${{totalClosed}}件決済完了)`;
            
            const retSign = totalReturn >= 0 ? '+' : '';
            const retElem = document.getElementById('aiReturnText');
            retElem.innerText = retSign + totalReturn.toFixed(1) + '%';
            retElem.className = 'display-5 fw-bold ' + (totalReturn >= 0 ? 'text-success' : 'text-danger');

            document.getElementById('aiTotalCountText').innerText = history.length + '件';
            document.getElementById('aiOpenCountText').innerText = '監視中: ' + (history.length - totalClosed) + '件';
        }}

        function deleteAISignal(index) {{
            if (confirm('この実測シグナルを消去しますか？')) {{
                const history = getLocalHistory();
                history.splice(index, 1);
                saveLocalHistory(history);
            }}
        }}

        function renderRealPortfolio() {{
            const portfolio = getLocalPortfolio();
            const tbody = document.getElementById('realPortfolioTableBody');
            tbody.innerHTML = '';
            
            let totalInvest = 0;
            let totalPnl = 0;

            if (!portfolio || portfolio.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">現在、実際の購入保有銘柄はありません。「➕ 画面から購入銘柄を即時追加」ボタンを押して登録してください。</td></tr>';
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

                totalInvest += invest;
                totalPnl += pnlY;

                const pnlCls = pnlY >= 0 ? 'text-success' : 'text-danger';
                const pnlSign = pnlY >= 0 ? '+' : '';

                tbody.innerHTML += `
                    <tr>
                        <td>${{item.buy_date || '-'}}</td>
                        <td><strong>${{item.name || item.ticker}}</strong></td>
                        <td>${{buyP.toLocaleString()}}円</td>
                        <td>${{shares.toLocaleString()}}株</td>
                        <td>${{(invest / 10000).toFixed(1)}}万円</td>
                        <td>${{currP.toLocaleString()}}円</td>
                        <td class="${{pnlCls}}"><strong>${{pnlSign}}${{Math.round(pnlY).toLocaleString()}}円 (${{pnlSign}}${{pnlP.toFixed(2)}}%)</strong></td>
                        <td><button class="btn btn-sm btn-outline-danger" onclick="deleteRealStock(${{index}})">削除</button></td>
                    </tr>
                `;
            }});

            document.getElementById('totalInvestText').innerText = (totalInvest / 10000).toFixed(1) + '万円';
            const totalSign = totalPnl >= 0 ? '+' : '';
            const totalPnlElem = document.getElementById('totalPnlText');
            totalPnlElem.innerText = totalSign + Math.round(totalPnl).toLocaleString() + '円';
            totalPnlElem.className = 'display-5 fw-bold ' + (totalPnl >= 0 ? 'text-success' : 'text-danger');
        }}

        function addRealStockFromForm() {{
            const ticker = document.getElementById('inputTicker').value.trim();
            let name = document.getElementById('inputName').value.trim();
            const buyPrice = parseFloat(document.getElementById('inputBuyPrice').value);
            const shares = parseInt(document.getElementById('inputShares').value);
            const buyDate = document.getElementById('inputBuyDate').value;

            if (!ticker || isNaN(buyPrice) || isNaN(shares) || !buyDate) {{
                alert('すべての必須項目を正しく入力してください。');
                return;
            }}

            if (!name) {{
                name = ticker;
            }}

            const newItem = {{
                id: 'user_' + Date.now(),
                ticker: ticker,
                name: name,
                buy_date: buyDate,
                buy_price: buyPrice,
                shares: shares,
                current_price: buyPrice,
                note: '画面から直接登録'
            }};

            const portfolio = getLocalPortfolio();
            portfolio.push(newItem);
            saveLocalPortfolio(portfolio);

            const modalElem = document.getElementById('addStockModal');
            const modal = bootstrap.Modal.getInstance(modalElem);
            if (modal) modal.hide();

            document.getElementById('addStockForm').reset();
        }}

        function deleteRealStock(index) {{
            if (confirm('この購入銘柄を削除しますか？')) {{
                const portfolio = getLocalPortfolio();
                portfolio.splice(index, 1);
                saveLocalPortfolio(portfolio);
            }}
        }}

        function copyPortfolioJSON() {{
            const portfolio = getLocalPortfolio();
            const str = JSON.stringify(portfolio, null, 2);
            navigator.clipboard.writeText(str).then(() => {{
                alert('現在画面で追加・編集したポートフォリオのJSONコードをクリップボードにコピーしました！AIへの連絡やサーバー同期にご利用いただけます。');
            }}).catch(err => {{
                prompt('以下をコピーしてください:', str);
            }});
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            document.getElementById('inputBuyDate').valueAsDate = new Date();
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
