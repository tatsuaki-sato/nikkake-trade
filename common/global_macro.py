import yfinance as yf
import pandas as pd
from common.cache_manager import get_cached_item, set_cached_item

GLOBAL_TICKERS = {
    "SOX": "^SOX",       # 米国フィラデルフィア半導体株指数
    "USDJPY": "JPY=X",   # ドル円為替レート
    "VIX": "^VIX",       # VIX恐怖指数
    "US10Y": "^TNX"      # 米国10年債利回り
}

def fetch_global_macro_data() -> dict:
    """
    グローバル・マクロ指標を取得・計算（キャッシュ有効期間: 1時間）
    """
    cached = get_cached_item("global_macro_data", ttl_seconds=3600)
    if cached:
        return cached

    macro_result = {
        "sox_change": 0.0,
        "usdjpy_change": 0.0,
        "vix_level": 20.0,
        "us10y_level": 4.0,
        "market_regime": "NEUTRAL"
    }
    
    try:
        data = yf.download(list(GLOBAL_TICKERS.values()), period="5d", progress=False)
        
        # SOX指数 1日変化率
        if GLOBAL_TICKERS["SOX"] in data['Close']:
            sox_c = data['Close'][GLOBAL_TICKERS["SOX"]].dropna()
            if len(sox_c) >= 2:
                macro_result["sox_change"] = float(((sox_c.iloc[-1] / sox_c.iloc[-2]) - 1) * 100)
                
        # ドル円 1日変化率
        if GLOBAL_TICKERS["USDJPY"] in data['Close']:
            jpy_c = data['Close'][GLOBAL_TICKERS["USDJPY"]].dropna()
            if len(jpy_c) >= 2:
                macro_result["usdjpy_change"] = float(((jpy_c.iloc[-1] / jpy_c.iloc[-2]) - 1) * 100)

        # VIX水準
        if GLOBAL_TICKERS["VIX"] in data['Close']:
            vix_c = data['Close'][GLOBAL_TICKERS["VIX"]].dropna()
            if len(vix_c) >= 1:
                macro_result["vix_level"] = float(vix_c.iloc[-1])

        # 米10年金利水準
        if GLOBAL_TICKERS["US10Y"] in data['Close']:
            us10y_c = data['Close'][GLOBAL_TICKERS["US10Y"]].dropna()
            if len(us10y_c) >= 1:
                macro_result["us10y_level"] = float(us10y_c.iloc[-1])

        # 市場モード判定 (Risk-On / Risk-Off)
        if macro_result["vix_level"] < 18.0:
            macro_result["market_regime"] = "RISK_ON (追い風)"
        elif macro_result["vix_level"] > 25.0:
            macro_result["market_regime"] = "RISK_OFF (警戒相場)"
        else:
            macro_result["market_regime"] = "NEUTRAL (中立)"
            
        set_cached_item("global_macro_data", macro_result)
    except Exception as e:
        print(f"マクロデータ取得エラー: {e}")

    return macro_result
