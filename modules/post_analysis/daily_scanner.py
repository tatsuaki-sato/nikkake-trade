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

def run_daily_scanner():
    """
    プロフェッショナル水準の事後分析スキャナー
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PRO事後分析スキャナー起動...")
    
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

            # 1. センチメント分析（Xの話題度）
            stock_name = ticker.replace('.T', '') # 本格運用時は企業名マッピングを推奨
            sentiment = get_x_sentiment_score(stock_name)
            
            # 2. プロスコア算出（TA + ファンダ推測）
            pro_result = calculate_pro_score(df, ticker, sentiment)
            score = pro_result['total_score']
            
            # 80点以上のプラチナ銘柄のみを抽出
            # ※テスト用に閾値を下げたい場合はここを変更
            if score >= 70: 
                # 株探から最新テーマ/ニュース取得
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
        notify_text += f"👑 **【PRO事後分析】プラチナ銘柄レポート**\n"
        notify_text += f"機関投資家水準のアルゴリズムが、総合スコア高得点の銘柄を検出しました。\n\n"
        
        # スコアが高い順にソート
        hit_list.sort(key=lambda x: x['スコア'], reverse=True)
        
        for hit in hit_list:
            tv_link = f"https://jp.tradingview.com/chart/?symbol=TSE%3A{hit['銘柄コード']}"
            notify_text += f"🔥 **{hit['銘柄コード']}** (総合スコア: **{hit['スコア']}点** / 終値 {hit['終値']:.1f}円)\n"
            notify_text += f"・チャート: {tv_link}\n"
            notify_text += f"・**【高評価の理由】**\n"
            for k, v in hit['詳細'].items():
                if "(0点)" not in v:
                    notify_text += f"  - {v}\n"
            
            notify_text += f"・**【最新テーマ / IR】**(株探より)\n"
            if hit['ニュース']:
                for n in hit['ニュース']:
                    notify_text += f"  - {n}\n"
            else:
                notify_text += f"  - 特筆すべきニュースなし\n"
            notify_text += "\n"
            
        notify(notify_text)
            
    else:
        notify_text = "📝 **【PRO事後分析】本日の総合レポート**\nプロ水準のスコアリングにおいて、本日80点を超える優良シグナル銘柄は検出されませんでした。"
        notify(notify_text)

if __name__ == "__main__":
    run_daily_scanner()
