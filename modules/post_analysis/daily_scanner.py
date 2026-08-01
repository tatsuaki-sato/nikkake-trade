import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os

# プロジェクトルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.notifier import notify
# 今後、news_scraper もモジュール配下に移動します
from modules.post_analysis.news_scraper import get_latest_news

# 代表的な日本株（テスト用）
TARGET_TICKERS = [
    "7203.T", "9984.T", "6920.T", "8035.T", "6861.T", 
    "7974.T", "6758.T", "9432.T", "8306.T", "4063.T", 
    "6098.T", "4502.T", "8001.T", "8031.T", "4568.T", 
    "6501.T", "6954.T", "3382.T", "6367.T", "7267.T"
]

def run_daily_scanner(vol_multiplier: float = 3.0, vol_ma_length: int = 10):
    """
    市場終了後（15:30）に実行される事後分析スキャナー
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 事後分析（デイリースキャナー）起動...")
    
    try:
        data = yf.download(TARGET_TICKERS, period="1mo", group_by="ticker", progress=False)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return

    hit_list = []
    
    for ticker in TARGET_TICKERS:
        try:
            df = data[ticker].copy()
            if len(df) < vol_ma_length + 1:
                continue
            df = df.dropna()
            if df.empty:
                continue

            df['Vol_MA'] = df['Volume'].rolling(window=vol_ma_length).mean()
            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            if pd.isna(latest_day['Vol_MA']):
                continue

            is_vol_surge = latest_day['Volume'] >= (latest_day['Vol_MA'] * vol_multiplier)
            is_price_up = latest_day['Close'] > prev_day['Close']
            
            if is_vol_surge and is_price_up:
                # ニュースの自動取得
                news = get_latest_news(ticker, limit=3)
                
                hit_list.append({
                    "銘柄コード": ticker.replace('.T', ''),
                    "終値": latest_day['Close'],
                    "出来高倍率": round(latest_day['Volume'] / latest_day['Vol_MA'], 1),
                    "ニュース": news
                })
        except Exception:
            continue

    # === 結果の出力と通知 ===
    notify_text = ""
    if len(hit_list) > 0:
        notify_text += f"📝 **【事後分析】本日の激アツ銘柄レポート**\n\n"
        
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"📈 **{hit['銘柄コード']}** (出来高 {hit['出来高倍率']}倍)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・**関連ニュース（動意づいた理由の候補）**:\n"
            
            if hit['ニュース']:
                for n in hit['ニュース']:
                    notify_text += f"  {n}\n"
            else:
                notify_text += f"  (※直近の主要ニュースは見つかりませんでした)\n"
            notify_text += "\n"
            
        notify(notify_text)
            
    else:
        notify_text = "📝 **【事後分析】本日の総合レポート**\n本日は異常な動き（出来高急増）をしている大型株は検出されませんでした。"
        notify(notify_text)

if __name__ == "__main__":
    run_daily_scanner(vol_multiplier=3.0, vol_ma_length=10)
