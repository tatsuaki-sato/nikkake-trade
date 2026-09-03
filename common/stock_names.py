import re as _re

STOCK_NAMES = {
    "7203": "トヨタ自動車",
    "9984": "ソフトバンクグループ",
    "6920": "レーザーテック",
    "8035": "東京エレクトロン",
    "6861": "キーエンス",
    "7974": "任天堂",
    "6758": "ソニーグループ",
    "9432": "NTT (日本電信電話)",
    "8306": "三菱UFJフィナンシャルG",
    "4063": "信越化学工業",
    "7011": "三菱重工業",
    "7012": "川崎重工業",
    "7013": "IHI",
    "2371": "カカクコム",
    "6857": "アドバンテスト",
    "6702": "富士通",
    "6701": "NEC",
    "3099": "三越伊勢丹HD",
    "4661": "オリエンタルランド",
    "9022": "JR東海",
    "1321": "日経225上場投信"
}

def _jquants_name(code: str) -> str:
    """J-Quantsの銘柄マスタ(全上場約4400社、24hキャッシュ)から企業名を引く。

    キー未設定・取得失敗時は空文字を返す(呼び出し側でフォールバックする)。
    """
    try:
        from common.market_data import jquants_available, get_equities_master
        if not jquants_available():
            return ""
        for row in get_equities_master():
            if row.get("Code", "")[:4] == code:
                return row.get("CoName", "")
    except Exception:
        pass
    return ""

def _yfinance_name(code: str) -> str:
    """yfinanceの .info から社名を引く(30日キャッシュ)。J-Quantsが使えない
    デプロイ環境や、マスタに載っていない新規上場銘柄の保険。多くは英語表記
    ("Aichi Financial Group, Inc.")だが、コードだけよりは分かる。"""
    try:
        from common.cache_manager import get_cached_item, set_cached_item
        cache_key = f"coname_{code}"
        cached = get_cached_item(cache_key, ttl_seconds=2592000)
        if cached is not None:
            return cached.get("name", "") if isinstance(cached, dict) else (cached or "")
        import yfinance as yf
        info = yf.Ticker(f"{code}.T").info or {}
        name = info.get("longName") or info.get("shortName") or ""
        if name:
            name = _re.sub(r",?\s*(Inc|Corp|Co|Ltd|Holdings|Company)\.?$", "", name).strip()
            set_cached_item(cache_key, {"name": name})
        return name
    except Exception:
        return ""

def get_company_sector(ticker: str) -> str:
    """東証の17業種区分(S17Nm)を返す。例: 「電機・精密」「銀行」「自動車・輸送機」。

    「AI」「半導体」のようなテーマ名は取引所の公式分類には無く(株探などが独自に
    付けている相場テーマ)、全銘柄を網羅した信頼できる対応表が無い。ここでは
    J-Quantsの銘柄マスタが持つ公式の業種区分を使う。テーマ経由で登録された
    シグナルは details["Theme"] に相場テーマが入るので、表示側で併用する。
    """
    code = ticker.replace('.T', '').strip()
    try:
        from common.market_data import jquants_available, get_equities_master
        if not jquants_available():
            return ""
        for row in get_equities_master():
            if row.get("Code", "")[:4] == code:
                return row.get("S17Nm", "") or ""
    except Exception:
        pass
    return ""

def get_company_name(ticker: str) -> str:
    """
    銘柄コード（例: 7203 または 7203.T）から日本企業名を取得。

    ハードコードの STOCK_NAMES は21銘柄しかなく、ウォッチリストが東証プライム
    全体を循環するようになってからは大半がコード表示のままになっていた。
    J-Quantsの銘柄マスタを優先し、使えない環境では従来の辞書に落とす。
    """
    code = ticker.replace('.T', '').strip()
    name = STOCK_NAMES.get(code) or _jquants_name(code) or _yfinance_name(code)
    if name:
        return f"{code} {name}"
    return code
