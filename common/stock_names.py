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

def get_company_name(ticker: str) -> str:
    """
    銘柄コード（例: 7203 または 7203.T）から日本企業名を取得。

    ハードコードの STOCK_NAMES は21銘柄しかなく、ウォッチリストが東証プライム
    全体を循環するようになってからは大半がコード表示のままになっていた。
    J-Quantsの銘柄マスタを優先し、使えない環境では従来の辞書に落とす。
    """
    code = ticker.replace('.T', '').strip()
    name = STOCK_NAMES.get(code) or _jquants_name(code)
    if name:
        return f"{code} {name}"
    return code
