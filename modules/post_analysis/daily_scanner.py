import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from common.cache_manager import get_cached_item, set_cached_item
from common.performance_tracker import record_signal, update_signal_performance
from modules.post_analysis.advanced_scraper import get_x_sentiment_score, get_kabutan_news, get_market_trending_themes, get_stock_financial_perks
from modules.post_analysis.quant_analyzer import evaluate_quant_factors

TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T"
]
BENCHMARK_TICKER = "1321.T"

def get_cached_financial_perks(ticker: str, close_price: float) -> dict:
    cache_key = f"perks_{ticker}"
    cached = get_cached_item(cache_key, ttl_seconds=604800)
    if cached:
        return cached
    data = get_stock_financial_perks(ticker, close_price)
    set_cached_item(cache_key, data)
    return data

def run_daily_scanner():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 売買判断ダッシュボード付きクオンツ事後分析起動...")
    
    # 既存の全シグナルの最新価格照合と勝敗判定
    update_signal_performance()
    
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

            close_price = float(stock_df.iloc[-1]['Close'])
            stock_name = ticker.replace('.T', '')
            sentiment = get_x_sentiment_score(stock_name)
            
            quant_result = evaluate_quant_factors(stock_df, market_df, ticker, sentiment)
            score = quant_result['total_score']
            
            if score >= 70: 
                news = get_kabutan_news(ticker)
                perks = get_cached_financial_perks(ticker, close_price)
                trade_plan = quant_result.get('trade_plan', {})
                
                # シグナル追跡データベースへの自動記録
                atr_series = stock_df['Close'].diff().abs().rolling(14).mean()
                atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else close_price * 0.02
                target_p = close_price + (3.0 * atr)
                stop_p = max(close_price - (2.0 * atr), 0)
                record_signal(ticker, close_price, target_p, stop_p, score, quant_result['details'])
                
                hit_list.append({
                    "銘柄コード": stock_name,
                    "終値": close_price,
                    "スコア": score,
                    "詳細": quant_result['details'],
                    "ニュース": news,
                    "最低購入金額": perks.get('min_investment', '要確認'),
                    "配当利回り": perks.get('dividend_yield', 'データなし'),
                    "株主優待": perks.get('yutai_info', 'なし'),
                    "PER": perks.get('per', 'データなし'),
                    "PBR": perks.get('pbr', 'データなし'),
                    "EPS成長率": perks.get('eps_growth', '要確認'),
                    "ボラティリティ": trade_plan.get('volatility', '要確認'),
                    "損切りライン": trade_plan.get('stop_loss', '要確認'),
                    "目標価格": trade_plan.get('target_price', '要確認'),
                    "リスクリワード": trade_plan.get('risk_reward_ratio', '1 : 1.5')
                })
        except Exception as e:
            print(f"銘柄分析エラー ({ticker}): {e}")
            continue

    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"🏛️ **【クオンツ売買判断ダッシュボード】プラチナ銘柄**\n\n"
        hit_list.sort(key=lambda x: x['スコア'], reverse=True)
        
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"📊 **{hit['銘柄コード']}** (クオンツスコア: **{hit['スコア']}点**)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・💵 **最低購入金額**: {hit['最低購入金額']} (終値 {hit['終値']:.1f}円)\n"
            notify_text += f"・💰 **配当利回り**: {hit['配当利回り']} / 🎁 **株主優待**: {hit['株主優待']}\n"
            notify_text += f"・⚖️ **割安度・成長性**: PER {hit['PER']} / PBR {hit['PBR']} / **EPS予想成長率**: {hit['EPS成長率']}\n"
            notify_text += f"・📉 **ボラティリティ**: {hit['ボラティリティ']}\n"
            notify_text += f"・🛑 **推奨損切りライン**: {hit['損切りライン']}\n"
            notify_text += f"・🎯 **目標価格 (利確)**: {hit['目標価格']} (RR比 {hit['リスクリワード']})\n"
            
            notify_text += f"・**【数理＆マクロ根拠】**\n"
            for k, v in hit['詳細'].items():
                if "[0点]" not in v:
                    notify_text += f"  - {v}\n"
            notify_text += "\n"
            
        notify(notify_text)
            
    else:
        theme_details = get_market_trending_themes()
        notify_text = "🏛️ **【クオンツ市況 ＆ 売買判断トレンドテーマ】**\n"
        notify_text += "本日は70点以上の高ファクター条件を満たす特定銘柄は検出されませんでしたが、現在市場で最も資金流入している注目テーマおよび代表関連株は以下の通りです：\n\n"
        notify_text += "🔥 **【市場注目テーマ TOP 5 ＆ 関連代表株】**\n"
        for i, item in enumerate(theme_details[:5], 1):
            stocks_str = ", ".join(item['stocks'])
            notify_text += f"{i}. **{item['theme']}**\n   └ 関連代表銘柄: {stocks_str}\n"
        notify_text += "\n※全自動で勝率・リスクリワード・全推奨シグナルを追跡データベースに自動記録しています。"
        
        notify(notify_text)

if __name__ == "__main__":
    run_daily_scanner()
