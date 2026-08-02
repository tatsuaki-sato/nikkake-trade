import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from modules.post_analysis.advanced_scraper import get_x_sentiment_score, get_kabutan_news
from modules.post_analysis.pro_analyzer import calculate_pro_score

TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T"
]

def run_predictor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PRO未来予測モジュール起動...")
    
    try:
        data = yf.download(TARGET_TICKERS, period="6mo", group_by="ticker", progress=False)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return

    hit_list = []
    
    for ticker in TARGET_TICKERS:
        try:
            df = data[ticker].copy()
            if len(df) < 50:
                continue
            df = df.dropna()

            sentiment = get_x_sentiment_score(ticker.replace('.T', ''))
            pro_result = calculate_pro_score(df, ticker, sentiment)
            score = pro_result['total_score']
            
            # 予測モジュールはテクニカル転換点（MACDなど）を重視
            is_turning_point = "MACDゴールデンクロス発生 (+20点)" in pro_result['details'].get('MACD', '') or \
                               "売られすぎからの反発 (+20点)" in pro_result['details'].get('RSI', '')
            
            if score >= 60 and is_turning_point:
                news = get_kabutan_news(ticker)
                hit_list.append({
                    "銘柄コード": ticker.replace('.T', ''),
                    "終値": df.iloc[-1]['Close'],
                    "スコア": score,
                    "詳細": pro_result['details'],
                    "ニュース": news
                })
        except Exception:
            continue

    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"🔮 **【PRO未来予測】本日の反発・トレンド転換 厳選銘柄**\n\n"
        hit_list.sort(key=lambda x: x['スコア'], reverse=True)
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"🚀 **{hit['銘柄コード']}** (PROスコア: **{hit['スコア']}点**)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・**【検知された転換シグナル】**\n"
            for k, v in hit['詳細'].items():
                if "(0点)" not in v:
                    notify_text += f"  - {v}\n"
            
            if hit['ニュース']:
                notify_text += f"・関連ニュース(株探): {hit['ニュース'][0]}\n"
            notify_text += "\n"
        notify(notify_text)
    else:
        notify_text = "🔮 **【PRO未来予測】**\n本日、プロ水準の厳しい基準を満たしたトレンド転換銘柄はありませんでした。"
        notify(notify_text)

if __name__ == "__main__":
    run_predictor()
