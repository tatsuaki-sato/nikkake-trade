import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from common.cache_manager import get_cached_item, set_cached_item
from modules.post_analysis.advanced_scraper import get_x_sentiment_score, get_kabutan_news, get_market_trending_themes, get_stock_financial_perks
from modules.post_analysis.quant_analyzer import evaluate_quant_factors

TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T"
]
BENCHMARK_TICKER = "1321.T"

def get_cached_financial_perks(ticker: str) -> dict:
    """配当利回り・優待をキャッシュ経由で取得（有効期間: 7日間）"""
    cache_key = f"perks_{ticker}"
    cached = get_cached_item(cache_key, ttl_seconds=604800)
    if cached:
        return cached
    data = get_stock_financial_perks(ticker)
    set_cached_item(cache_key, data)
    return data

def run_daily_scanner():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] グローバル・クオンツ事後分析スキャナー起動...")
    
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

            stock_name = ticker.replace('.T', '')
            sentiment = get_x_sentiment_score(stock_name)
            
            quant_result = evaluate_quant_factors(stock_df, market_df, ticker, sentiment)
            score = quant_result['total_score']
            
            if score >= 70: 
                news = get_kabutan_news(ticker)
                financial_perks = get_cached_financial_perks(ticker)
                
                hit_list.append({
                    "銘柄コード": ticker.replace('.T', ''),
                    "終値": stock_df.iloc[-1]['Close'],
                    "スコア": score,
                    "詳細": quant_result['details'],
                    "ニュース": news,
                    "配当利回り": financial_perks.get('dividend_yield', 'データなし'),
                    "株主優待": financial_perks.get('yutai_info', 'なし')
                })
        except Exception as e:
            print(f"銘柄分析エラー ({ticker}): {e}")
            continue

    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"🏛️ **【グローバル・クオンツ分析】プラチナ銘柄**\n"
        notify_text += f"米国マクロ連動・EDINET開示・残差モメンタム・TTMスクイーズによる判定です。\n\n"
        
        hit_list.sort(key=lambda x: x['スコア'], reverse=True)
        
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"📊 **{hit['銘柄コード']}** (クオンツスコア: **{hit['スコア']}点** / 終値 {hit['終値']:.1f}円)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・💰 **配当利回り**: {hit['配当利回り']} / 🎁 **株主優待**: {hit['株主優待']}\n"
            notify_text += f"・**【数理＆マクロ判定要因】**\n"
            for k, v in hit['詳細'].items():
                if "[0点]" not in v:
                    notify_text += f"  - {v}\n"
            
            notify_text += f"・**【適時開示 / 株探ニュース】**\n"
            if hit['ニュース']:
                for n in hit['ニュース']:
                    notify_text += f"  - {n}\n"
            else:
                notify_text += f"  - 特筆ニュースなし\n"
            notify_text += "\n"
            
        notify(notify_text)
            
    else:
        theme_details = get_market_trending_themes()
        notify_text = "🏛️ **【グローバル・クオンツ分析】本日の市況・トレンドテーマ＆関連株**\n"
        notify_text += "本日は高ファクター条件を満たす特定銘柄は検出されませんでしたが、現在市場で最も資金流入している注目テーマおよび代表関連株は以下の通りです：\n\n"
        notify_text += "🔥 **【市場注目テーマ TOP 5 ＆ 関連代表株】**\n"
        for i, item in enumerate(theme_details[:5], 1):
            stocks_str = ", ".join(item['stocks'])
            notify_text += f"{i}. **{item['theme']}**\n   └ 関連代表銘柄: {stocks_str}\n"
        notify_text += "\n※米国マクロ環境・EDINET大量保有開示を全自動で継続監視しています。"
        
        notify(notify_text)

if __name__ == "__main__":
    run_daily_scanner()
