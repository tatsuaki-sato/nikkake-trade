import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.quant_math import calculate_residual_momentum, calculate_ttm_squeeze, calculate_obv, calculate_atr
from common.global_macro import fetch_global_macro_data
from modules.post_analysis.edinet_scraper import check_edinet_large_holdings

SEMICON_TICKERS = ["6920.T", "8035.T", "6857.T", "6146.T"]
EXPORTER_TICKERS = ["7203.T", "7267.T", "6758.T"]

def evaluate_quant_factors(stock_df: pd.DataFrame, market_df: pd.DataFrame, ticker: str, x_sentiment_score: int) -> dict:
    """
    グローバルマクロ ＆ EDINET 5%ルール ＆ 7大売買判断メトリクス統合エンジン
    """
    if len(stock_df) < 50:
        return {"total_score": 0, "details": {}, "trade_plan": {}}
        
    score = 0
    details = {}
    
    macro_data = fetch_global_macro_data()
    edinet_info = check_edinet_large_holdings(ticker)

    # 1. 固有モメンタム
    res_mom = calculate_residual_momentum(stock_df, market_df)
    if res_mom >= 2.0:
        score += 30
        details['Residual_Momentum'] = f"固有モメンタム極めて強力 (z-score: {res_mom:.2f}) [+30点]"
    elif res_mom >= 1.0:
        score += 20
        details['Residual_Momentum'] = f"固有モメンタム上昇傾向 (z-score: {res_mom:.2f}) [+20点]"
    elif res_mom > 0:
        score += 10
        details['Residual_Momentum'] = f"固有モメンタムプラス圏 (z-score: {res_mom:.2f}) [+10点]"
    else:
        details['Residual_Momentum'] = f"固有モメンタム弱勢 (z-score: {res_mom:.2f}) [0点]"

    # 2. TTM Squeeze
    squeeze_df = calculate_ttm_squeeze(stock_df)
    latest_sq = squeeze_df.iloc[-1]
    
    if latest_sq['Squeeze_Fired']:
        score += 25
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ解除(上放れ) [+25点]"
    elif latest_sq['Squeeze_On']:
        score += 15
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ中(エネルギー蓄積) [+15点]"
    elif latest_sq['Close'] > latest_sq['BB_Upper']:
        score += 10
        details['Volatility_Squeeze'] = "ボリンジャーバンド2σ上抜け継続 [+10点]"
    else:
        details['Volatility_Squeeze'] = "ボラティリティ定常状態 [0点]"

    # 3. OBV & 需給
    obv_series = calculate_obv(stock_df)
    obv_ma = obv_series.rolling(20).mean()
    if obv_series.iloc[-1] > obv_ma.iloc[-1] and obv_series.iloc[-1] > obv_series.iloc[-5]:
        score += 20
        details['Supply_Demand'] = "OBV出来高集積ライン上昇(機関大口買い) [+20点]"
    elif stock_df['Volume'].iloc[-1] > stock_df['Volume'].rolling(20).mean().iloc[-1] * 2:
        score += 10
        details['Supply_Demand'] = "出来高急増 [+10点]"
    else:
        details['Supply_Demand'] = "需給シグナルなし [0点]"

    # 4. マクロ
    if ticker in SEMICON_TICKERS and macro_data['sox_change'] > 1.5:
        score += 15
        details['Global_Macro'] = f"米国SOX指数急騰 (+{macro_data['sox_change']:.1f}%) [+15点]"
    elif ticker in EXPORTER_TICKERS and macro_data['usdjpy_change'] > 0.5:
        score += 15
        details['Global_Macro'] = f"ドル円円安進行 (+{macro_data['usdjpy_change']:.1f}%) [+15点]"
    elif "RISK_ON" in macro_data['market_regime']:
        score += 10
        details['Global_Macro'] = f"グローバルVIX低水準 ({macro_data['vix_level']:.1f}) [+10点]"
    else:
        details['Global_Macro'] = f"マクロ環境: {macro_data['market_regime']} [0点]"

    # 5. X センチメント
    sentiment_score = int(x_sentiment_score * 0.10)
    score += sentiment_score
    details['Social_Sentiment'] = f"X話題度スコア ({x_sentiment_score}) [+{sentiment_score}点]"

    # 6. EDINET ボーナス
    if edinet_info["has_5percent_report"]:
        score += 30
        details['EDINET_Disclosure'] = f"📜 【公的開示】{edinet_info['details']} [+30点ボーナス]"

    # 🎯 7大売買判断メトリクス（ATR目標価格・損切りライン計算）
    close = float(stock_df.iloc[-1]['Close'])
    atr_series = calculate_atr(stock_df)
    atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else close * 0.02
    
    volatility_pct = (atr / close) * 100
    stop_loss = max(close - (2.0 * atr), 0)
    stop_loss_pct = ((stop_loss - close) / close) * 100
    
    target_price = close + (3.0 * atr)
    target_price_pct = ((target_price - close) / close) * 100
    
    trade_plan = {
        "close_price": f"{close:,.1f}円",
        "volatility": f"日次±{atr:.1f}円 ({volatility_pct:.1f}%)",
        "stop_loss": f"{stop_loss:,.1f}円 ({stop_loss_pct:.1f}%)",
        "target_price": f"{target_price:,.1f}円 (+{target_price_pct:.1f}%)",
        "risk_reward_ratio": "1 : 1.5 (勝負価値あり)"
    }

    return {
        "total_score": min(score, 100),
        "details": details,
        "trade_plan": trade_plan
    }
