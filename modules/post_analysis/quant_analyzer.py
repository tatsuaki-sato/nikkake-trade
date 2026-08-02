import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.quant_math import calculate_residual_momentum, calculate_ttm_squeeze, calculate_obv, calculate_atr

def evaluate_quant_factors(stock_df: pd.DataFrame, market_df: pd.DataFrame, ticker: str, x_sentiment_score: int) -> dict:
    """
    クオンツファイナンス学術論文に基づく5ファクター評価モデル
    100点満点で総合スコアを評価
    """
    if len(stock_df) < 50:
        return {"total_score": 0, "details": {}}
        
    score = 0
    details = {}
    
    # 1. 固有モメンタム (Residual Momentum) - 配点 30点
    res_mom = calculate_residual_momentum(stock_df, market_df)
    if res_mom >= 2.0:
        mom_score = 30
        details['Residual_Momentum'] = f"固有モメンタム極めて強力 (z-score: {res_mom:.2f}) [+30点]"
    elif res_mom >= 1.0:
        mom_score = 20
        details['Residual_Momentum'] = f"固有モメンタム上昇傾向 (z-score: {res_mom:.2f}) [+20点]"
    elif res_mom > 0:
        mom_score = 10
        details['Residual_Momentum'] = f"固有モメンタムプラス圏 (z-score: {res_mom:.2f}) [+10点]"
    else:
        mom_score = 0
        details['Residual_Momentum'] = f"固有モメンタム弱勢 (z-score: {res_mom:.2f}) [0点]"
    score += mom_score

    # 2. ボラティリティ・スクイーズ (TTM Squeeze / Keltner-Bollinger) - 配点 25点
    squeeze_df = calculate_ttm_squeeze(stock_df)
    latest_sq = squeeze_df.iloc[-1]
    
    if latest_sq['Squeeze_Fired']:
        sq_score = 25
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ解除(上放れブレイクアウト発火) [+25点]"
    elif latest_sq['Squeeze_On']:
        sq_score = 15
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ中(エネルギー極大蓄積) [+15点]"
    elif latest_sq['Close'] > latest_sq['BB_Upper']:
        sq_score = 10
        details['Volatility_Squeeze'] = "ボリンジャーバンド2σ上抜け継続 [+10点]"
    else:
        sq_score = 0
        details['Volatility_Squeeze'] = "ボラティリティ定常状態 [0点]"
    score += sq_score

    # 3. OBV & 出来高集積 (Supply & Demand / OBV Divergence) - 配点 20点
    obv_series = calculate_obv(stock_df)
    obv_ma = obv_series.rolling(20).mean()
    
    if obv_series.iloc[-1] > obv_ma.iloc[-1] and obv_series.iloc[-1] > obv_series.iloc[-5]:
        obv_score = 20
        details['Supply_Demand'] = "OBV出来高集積ライン上昇(大口・機関購入パターン) [+20点]"
    elif stock_df['Volume'].iloc[-1] > stock_df['Volume'].rolling(20).mean().iloc[-1] * 2:
        obv_score = 10
        details['Supply_Demand'] = "出来高が20日平均の2倍以上増額 [+10点]"
    else:
        obv_score = 0
        details['Supply_Demand'] = "需給シグナルなし [0点]"
    score += obv_score

    # 4. ソーシャル / X センチメント (Social Momentum Anomaly) - 配点 15点
    sentiment_score = int(x_sentiment_score * 0.15)
    score += sentiment_score
    details['Social_Sentiment'] = f"X(Twitter)ソーシャル熱狂度スコア (数値: {x_sentiment_score}) [+{sentiment_score}点]"

    # 5. ATR リスク調整度 (Risk-Adjusted Volatility Ratio) - 配点 10点
    atr_series = calculate_atr(stock_df)
    current_atr = atr_series.iloc[-1]
    atr_ma = atr_series.rolling(30).mean().iloc[-1]
    
    # ノイズの少ないクリーンなトレンドか（ATRが大きすぎず安定しているか）
    if current_atr <= atr_ma * 1.5 and stock_df['Close'].iloc[-1] > stock_df['Close'].iloc[-20]:
        risk_score = 10
        details['ATR_Risk'] = f"リスク調整後ボラティリティ安定・クリーンなトレンド [+10点]"
    else:
        risk_score = 0
        details['ATR_Risk'] = "ボラティリティ高ノイズ状態 [0点]"
    score += risk_score

    return {
        "total_score": min(score, 100),
        "details": details
    }
