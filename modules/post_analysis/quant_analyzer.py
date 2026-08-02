import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.quant_math import calculate_residual_momentum, calculate_ttm_squeeze, calculate_obv, calculate_atr
from common.global_macro import fetch_global_macro_data
from modules.post_analysis.edinet_scraper import check_edinet_large_holdings

# 半導体関連銘柄
SEMICON_TICKERS = ["6920.T", "8035.T", "6857.T", "6146.T"]
# 輸出・自動車関連銘柄
EXPORTER_TICKERS = ["7203.T", "7267.T", "6758.T"]

def evaluate_quant_factors(stock_df: pd.DataFrame, market_df: pd.DataFrame, ticker: str, x_sentiment_score: int) -> dict:
    """
    グローバルマクロ ＆ EDINET 5%ルール ＆ 5ファクター統合評価エンジン
    """
    if len(stock_df) < 50:
        return {"total_score": 0, "details": {}}
        
    score = 0
    details = {}
    
    # グローバルマクロデータ取得
    macro_data = fetch_global_macro_data()
    # EDINET 5%ルール / 自社株買い開示チェック
    edinet_info = check_edinet_large_holdings(ticker)

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

    # 2. ボラティリティ・スクイーズ (TTM Squeeze) - 配点 25点
    squeeze_df = calculate_ttm_squeeze(stock_df)
    latest_sq = squeeze_df.iloc[-1]
    
    if latest_sq['Squeeze_Fired']:
        sq_score = 25
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ解除(上放れブレイクアウト) [+25点]"
    elif latest_sq['Squeeze_On']:
        sq_score = 15
        details['Volatility_Squeeze'] = "ボラティリティ・スクイーズ中(エネルギー蓄積) [+15点]"
    elif latest_sq['Close'] > latest_sq['BB_Upper']:
        sq_score = 10
        details['Volatility_Squeeze'] = "ボリンジャーバンド2σ上抜け継続 [+10点]"
    else:
        sq_score = 0
        details['Volatility_Squeeze'] = "ボラティリティ定常状態 [0点]"
    score += sq_score

    # 3. OBV & 需給集積 - 配点 20点
    obv_series = calculate_obv(stock_df)
    obv_ma = obv_series.rolling(20).mean()
    if obv_series.iloc[-1] > obv_ma.iloc[-1] and obv_series.iloc[-1] > obv_series.iloc[-5]:
        obv_score = 20
        details['Supply_Demand'] = "OBV出来高集積ライン上昇(機関大口買い) [+20点]"
    elif stock_df['Volume'].iloc[-1] > stock_df['Volume'].rolling(20).mean().iloc[-1] * 2:
        obv_score = 10
        details['Supply_Demand'] = "出来高急増 [+10点]"
    else:
        obv_score = 0
        details['Supply_Demand'] = "需給シグナルなし [0点]"
    score += obv_score

    # 4. グローバル・マクロ連動評価 - 配点 15点
    macro_score = 0
    if ticker in SEMICON_TICKERS and macro_data['sox_change'] > 1.5:
        macro_score = 15
        details['Global_Macro'] = f"米国SOX指数急騰 (+{macro_data['sox_change']:.1f}%) による強力追い風 [+15点]"
    elif ticker in EXPORTER_TICKERS and macro_data['usdjpy_change'] > 0.5:
        macro_score = 15
        details['Global_Macro'] = f"ドル円円安進行 (+{macro_data['usdjpy_change']:.1f}%) による業績追い風 [+15点]"
    elif "RISK_ON" in macro_data['market_regime']:
        macro_score = 10
        details['Global_Macro'] = f"グローバルVIX低水準 ({macro_data['vix_level']:.1f}) リスクオン環境 [+10点]"
    else:
        details['Global_Macro'] = f"グローバルマクロ環境: {macro_data['market_regime']} [0点]"
    score += macro_score

    # 5. X センチメント - 配点 10点
    sentiment_score = int(x_sentiment_score * 0.10)
    score += sentiment_score
    details['Social_Sentiment'] = f"X話題度スコア ({x_sentiment_score}) [+{sentiment_score}点]"

    # 🔥 ボーナス: 金融庁EDINET 5%ルール大量保有 / 自社株買い開示 - ボーナス +30点
    if edinet_info["has_5percent_report"]:
        score += 30
        details['EDINET_Disclosure'] = f"📜 【公的開示】{edinet_info['details']} [+30点ボーナス]"

    return {
        "total_score": min(score, 100),
        "details": details,
        "macro_info": macro_data
    }
