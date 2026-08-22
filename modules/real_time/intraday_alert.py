import yfinance as yf
import pandas as pd
from datetime import datetime
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from common.watchlist import get_target_tickers

def run_intraday_alert(vol_spike_multiplier: float = 10.0):
    """
    場中（9:00〜15:00）に定期実行され、5分足ベースで突発的な出来高急増を検知する
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] リアルタイム検知（分足スパイク）起動...")

    # このワークフローにはDB認証情報が無いためフォールバックのデフォルトリストになる。
    # ウォッチリストをDBで更新した場合は intraday_alert.yml にも Secrets を追加すること。
    target_tickers = get_target_tickers()

    try:
        # 1日のデータを5分足で取得
        data = yf.download(target_tickers, period="1d", interval="5m", group_by="ticker", progress=False)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return

    for ticker in target_tickers:
        try:
            df = data[ticker].copy()
            if len(df) < 2:
                continue
            df = df.dropna()

            # 直近の5分足とその1つ前の5分足を比較
            latest_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]
            
            # 前の5分足の出来高が0だと計算できないので回避
            if prev_candle['Volume'] == 0:
                continue

            vol_ratio = latest_candle['Volume'] / prev_candle['Volume']
            is_price_up = latest_candle['Close'] > latest_candle['Open'] # 陽線であること
            
            if vol_ratio >= vol_spike_multiplier and is_price_up:
                notify_text = (
                    f"🚨 **【速報】局所的な急騰を検知！** 🚨\n"
                    f"銘柄: **{ticker.replace('.T', '')}**\n"
                    f"状態: たった今の5分間で、直前の {vol_ratio:.1f}倍 の買い（出来高）が入りました！\n"
                    f"現在値: {latest_candle['Close']:.1f}円\n"
                    f"チャート: https://jp.tradingview.com/chart/?symbol=TSE%3A{ticker.replace('.T', '')}"
                )
                notify(notify_text)
                
        except Exception:
            continue

if __name__ == "__main__":
    # ※テスト用：実際は cron やループで5分に1回呼び出します
    # 強制的に反応させるため倍率を下げてテストすることも可能です
    run_intraday_alert(vol_spike_multiplier=10.0)
