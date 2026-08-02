import numpy as np
import pandas as pd

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) を計算
    """
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_ttm_squeeze(df: pd.DataFrame, bb_period: int = 20, bb_std: float = 2.0, kc_period: int = 20, kc_mult: float = 1.5) -> pd.DataFrame:
    """
    Keltner Channel & Bollinger Bands Squeeze (TTM Squeeze)
    ボリンジャーバンドがケルトナーチャネルの内部に収縮しているかを判定。
    """
    res = df.copy()
    
    # 1. ボリンジャーバンド
    sma = res['Close'].rolling(window=bb_period).mean()
    std = res['Close'].rolling(window=bb_period).std()
    res['BB_Upper'] = sma + (std * bb_std)
    res['BB_Lower'] = sma - (std * bb_std)
    
    # 2. ケルトナーチャネル
    res['ATR'] = calculate_atr(res, period=kc_period)
    res['KC_Upper'] = sma + (res['ATR'] * kc_mult)
    res['KC_Lower'] = sma - (res['ATR'] * kc_mult)
    
    # Squeeze 状態: BBの上下限が KCの上下限の内側にあること
    res['Squeeze_On'] = (res['BB_Lower'] > res['KC_Lower']) & (res['BB_Upper'] < res['KC_Upper'])
    # Squeeze 解除 (Fired): 前日 Squeeze ON で、当日 OFF
    res['Squeeze_Fired'] = res['Squeeze_On'].shift(1) & (~res['Squeeze_On'])
    
    return res

def calculate_obv(df: pd.DataFrame) -> pd.Series:
    """
    On-Balance Volume (OBV) の計算
    """
    close = df['Close']
    volume = df['Volume']
    
    direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
    obv = (volume * direction).cumsum()
    return pd.Series(obv, index=df.index)

def calculate_residual_momentum(stock_df: pd.DataFrame, market_df: pd.DataFrame) -> float:
    """
    残差モメンタム（Residual Momentum）の計算
    市場ベンチマーク（TOPIX/日経平均等）のベータを除去した固有のモメンタムを回帰分析で算出
    """
    try:
        # 日次リターン
        s_ret = stock_df['Close'].pct_change().dropna()
        m_ret = market_df['Close'].pct_change().dropna()
        
        # 共通日付にインデックスを揃える
        common_idx = s_ret.index.intersection(m_ret.index)
        if len(common_idx) < 30:
            return 0.0
            
        s_ret = s_ret.loc[common_idx]
        m_ret = m_ret.loc[common_idx]
        
        # 1ヶ月の反転効果（直近20営業日）を除外し、過去250営業日〜20営業日の期間で回帰分析
        if len(s_ret) > 20:
            s_ret_trimmed = s_ret.iloc[:-20]
            m_ret_trimmed = m_ret.iloc[:-20]
        else:
            s_ret_trimmed = s_ret
            m_ret_trimmed = m_ret
            
        # OLS (最小二乗法): Stock_Return = alpha + beta * Market_Return + epsilon
        cov = np.cov(s_ret_trimmed, m_ret_trimmed)[0][1]
        var_m = np.var(m_ret_trimmed)
        beta = cov / var_m if var_m != 0 else 1.0
        
        # 残差リターン (Residual Return)
        residuals = s_ret_trimmed - (beta * m_ret_trimmed)
        
        # 標準化された残差モメンタム (Sharpe-like ratio of residuals)
        res_mom = residuals.sum() / (residuals.std() * np.sqrt(len(residuals))) if residuals.std() != 0 else 0.0
        return float(res_mom)
    except Exception as e:
        print(f"残差モメンタム計算エラー: {e}")
        return 0.0
