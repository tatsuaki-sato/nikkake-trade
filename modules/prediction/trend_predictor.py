import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from modules.post_analysis.advanced_scraper import get_x_sentiment_score, get_kabutan_news
from modules.post_analysis.quant_analyzer import evaluate_quant_factors

TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T"
]
BENCHMARK_TICKER = "1321.T"

def run_predictor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] クオンツ未来予測モジュール起動...")
    
    tickers_to_fetch = TARGET_TICKERS + [BENCHMARK_TICKER]
    try:
        data = yf.download(tickers_to_fetch, period="1y", group_by="ticker", progress=False)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return

    market_df = data[BENCHMARK_TICKER].copy().dropna()
    hit_list = []
    
    for ticker in TARGET_TICKERS:
        try:
            stock_df = data[ticker].copy().dropna()
            if len(stock_df) < 50:
                continue

            sentiment = get_x_sentiment_score(ticker.replace('.T', ''))
            quant_result = evaluate_quant_factors(stock_df, market_df, ticker, sentiment)
            score = quant_result['total_score']
            
            # ボラティリティスクイーズ発火（Squeeze Fired）または残差モメンタム高数値を予測条件とする
            is_quant_prediction = "ボラティリティ・スクイーズ解除" in quant_result['details'].get('Volatility_Squeeze', '') or \
                                  "固有モメンタム極めて強力" in quant_result['details'].get('Residual_Momentum', '')
            
            if score >= 60 and is_quant_prediction:
                news = get_kabutan_news(ticker)
                hit_list.append({
                    "銘柄コード": ticker.replace('.T', ''),
                    "終値": stock_df.iloc[-1]['Close'],
                    "スコア": score,
                    "詳細": quant_result['details'],
                    "ニュース": news
                })
        except Exception as e:
            print(f"予測分析エラー ({ticker}): {e}")
            continue

    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"🔮 **【クオンツ未来予測】スクイーズ解除・固有モメンタム上昇 厳選銘柄**\n\n"
        hit_list.sort(key=lambda x: x['スコア'], reverse=True)
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"🚀 **{hit['銘柄コード']}** (クオンツスコア: **{hit['スコア']}点**)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・**【数理シグナル要因】**\n"
            for k, v in hit['詳細'].items():
                if "[0点]" not in v:
                    notify_text += f"  - {v}\n"
            
            if hit['ニュース']:
                notify_text += f"・適時ニュース: {hit['ニュース'][0]}\n"
            notify_text += "\n"
        notify(notify_text)
    else:
        notify_text = "🔮 **【クオンツ未来予測】**\n本日、スクイーズブレイクアウト条件を満たす定量的ブレイク銘柄はありませんでした。"
        notify(notify_text)

if __name__ == "__main__":
    run_predictor()
