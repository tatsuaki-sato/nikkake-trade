import pandas as pd
import numpy as np
try:
    from ta.trend import MACD
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands
except ImportError:
    pass # 依存関係は要インストール

def calculate_pro_score(df: pd.DataFrame, ticker: str, x_sentiment_score: int) -> dict:
    """
    テクニカル、ファンダメンタル、センチメントを総合した
    100点満点のプロフェッショナル・スコアを算出します。
    """
    if len(df) < 50:
        return {"total_score": 0, "details": {}}
        
    # 最新のデータ
    latest = df.iloc[-1]
    
    score = 0
    details = {}
    
    # 1. テクニカル分析 (TA) - 配点 60点
    # --- MACD (配点20点) ---
    macd = MACD(close=df['Close'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    df['MACD_Diff'] = macd.macd_diff()
    
    # MACDがシグナルを上抜けた（ゴールデンクロス）か、ヒストグラムが拡大中なら加点
    if df['MACD_Diff'].iloc[-1] > 0 and df['MACD_Diff'].iloc[-2] <= 0:
        score += 20
        details['MACD'] = "MACDゴールデンクロス発生 (+20点)"
    elif df['MACD_Diff'].iloc[-1] > df['MACD_Diff'].iloc[-2] > 0:
        score += 10
        details['MACD'] = "MACD上昇トレンド継続 (+10点)"
    else:
        details['MACD'] = "MACDシグナルなし (0点)"
        
    # --- RSI (配点20点) ---
    rsi = RSIIndicator(close=df['Close'], window=14)
    df['RSI'] = rsi.rsi()
    current_rsi = df['RSI'].iloc[-1]
    
    # RSIが売られすぎ(30以下)から反発、またはモメンタム良好(50~70)
    if 30 < current_rsi < 40 and df['RSI'].iloc[-2] <= 30:
        score += 20
        details['RSI'] = f"RSI({current_rsi:.1f}) 売られすぎからの反発 (+20点)"
    elif 50 <= current_rsi <= 70:
        score += 10
        details['RSI'] = f"RSI({current_rsi:.1f}) 上昇モメンタム良好 (+10点)"
    else:
        details['RSI'] = f"RSI({current_rsi:.1f}) 特筆すべきシグナルなし (0点)"
        
    # --- ボリンジャーバンド (配点20点) ---
    bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
    df['BB_High'] = bb.bollinger_hband()
    df['BB_Low'] = bb.bollinger_lband()
    df['BB_Width'] = bb.bollinger_wband()
    
    # スクイーズ（収縮）からの上放れ（エクスパンション初動）を狙う
    current_close = latest['Close']
    if current_close > df['BB_High'].iloc[-1]:
        score += 20
        details['BB'] = "ボリンジャーバンド +2σ突破（バンドウォーク初動） (+20点)"
    elif df['BB_Width'].iloc[-1] < df['BB_Width'].rolling(window=10).mean().iloc[-1]:
        score += 5
        details['BB'] = "ボリンジャーバンド スクイーズ（エネルギー蓄積中） (+5点)"
    else:
        details['BB'] = "ボリンジャーバンド シグナルなし (0点)"
        
    # 2. センチメント分析 (X / Yahooリアルタイム検索) - 配点 20点
    # x_sentiment_score は 0〜100 の値。これを0〜20点にスケールダウン
    sentiment_bonus = int(x_sentiment_score * 0.2)
    score += sentiment_bonus
    details['Sentiment'] = f"X話題度スコア変換 (+{sentiment_bonus}点)"
    
    # 3. 需給・ファンダメンタルズ推定 - 配点 20点
    # 出来高の急増（機関投資家の介入）を需給スコアとする
    vol_ma = df['Volume'].rolling(window=20).mean().iloc[-1]
    current_vol = latest['Volume']
    if current_vol > vol_ma * 3:
        score += 20
        details['Volume'] = f"出来高が通常の3倍以上（機関買いの可能性） (+20点)"
    elif current_vol > vol_ma * 1.5:
        score += 10
        details['Volume'] = f"出来高増加傾向 (+10点)"
    else:
        details['Volume'] = "出来高平常 (0点)"
        
    return {
        "total_score": min(score, 100), # MAX100点
        "details": details
    }
