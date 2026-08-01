import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from modules.post_analysis.news_scraper import get_latest_news

TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T", 
    "6098.T", "4502.T", "8001.T", "8031.T", "4568.T", 
    "6501.T", "6954.T", "3382.T", "6367.T", "7267.T"
]

def run_predictor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 未来予測（ゴールデンクロス検知）起動...")
    
    try:
        data = yf.download(TARGET_TICKERS, period="3mo", group_by="ticker", progress=False)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return

    hit_list = []
    
    for ticker in TARGET_TICKERS:
        try:
            df = data[ticker].copy()
            if len(df) < 26:
                continue
            df = df.dropna()

            # 短期線（5日）と長期線（25日）を計算
            df['SMA_5'] = df['Close'].rolling(window=5).mean()
            df['SMA_25'] = df['Close'].rolling(window=25).mean()
            
            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            if pd.isna(latest_day['SMA_25']):
                continue

            # ゴールデンクロスの条件：
            # 1. 前日は 短期線 < 長期線 だった
            # 2. 当日は 短期線 >= 長期線 になった（クロスした）
            is_golden_cross = (prev_day['SMA_5'] < prev_day['SMA_25']) and (latest_day['SMA_5'] >= latest_day['SMA_25'])
            
            # テスト用に条件を緩和する場合は以下を有効化
            # is_golden_cross = True if latest_day['SMA_5'] > latest_day['SMA_25'] else False
            
            if is_golden_cross:
                news = get_latest_news(ticker, limit=2)
                hit_list.append({
                    "銘柄コード": ticker.replace('.T', ''),
                    "終値": latest_day['Close'],
                    "ニュース": news
                })
        except Exception:
            continue

    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"🔮 **【未来予測】本日のゴールデンクロス（上昇トレンド転換）銘柄**\n\n"
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"🚀 **{hit['銘柄コード']}** (終値: {hit['終値']:.1f}円)\n"
            notify_text += f"・チャート: {tv_link}\n"
            if hit['ニュース']:
                notify_text += f"・関連ニュース: {hit['ニュース'][0]}\n"
            notify_text += "\n"
        notify(notify_text)
    else:
        notify_text = "🔮 **【未来予測】**\n本日、新たにゴールデンクロスを形成した大型株はありませんでした。"
        notify(notify_text)

if __name__ == "__main__":
    run_predictor()
