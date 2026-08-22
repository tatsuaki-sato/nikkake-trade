"""
common/market_data.py
J-Quants API V2 (JPX公式) の薄いクライアント。

環境変数 JQUANTS_API_KEY (ダッシュボードで発行するAPIキー。x-api-key ヘッダーで送る)。
Freeプランはデータが12週遅延・過去2年分のため、当日の価格取得には使えない。
当日価格は従来どおり yfinance を使い、こちらはユニバース選定・ファクター計算・
バックテストの基盤として使う(v2設計 Layer 1)。

銘柄コードは5桁 ("7203" → "72030")。ここでは4桁/".T"付きも受け付けて変換する。
"""
import os
import time
import requests

from common.cache_manager import get_cached_item, set_cached_item

BASE_URL = "https://api.jquants.com/v2"

def jquants_available() -> bool:
    return bool(os.environ.get("JQUANTS_API_KEY"))

def _normalize_code(code: str) -> str:
    """"7203" / "7203.T" / "72030" → J-Quants 5桁コード"""
    code = code.replace(".T", "").strip()
    if len(code) == 4:
        code += "0"
    return code

def _get(path: str, params: dict = None) -> dict:
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY 環境変数が設定されていません")
    headers = {"x-api-key": api_key}
    resp = requests.get(f"{BASE_URL}{path}", params=params or {}, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def _get_paginated(path: str, params: dict = None, data_key: str = "data", max_pages: int = 50) -> list:
    """pagination_key を辿って全件取得"""
    params = dict(params or {})
    rows = []
    for _ in range(max_pages):
        d = _get(path, params)
        rows.extend(d.get(data_key, []))
        pk = d.get("pagination_key")
        if not pk:
            break
        params["pagination_key"] = pk
        time.sleep(0.2)
    return rows

def get_equities_master(code: str = None, use_cache: bool = True) -> list:
    """上場銘柄マスタ。code省略で全上場銘柄(約4000件、24hキャッシュ)。

    各行: Code(5桁), CoName, S17/S33(業種), ScaleCat(TOPIX規模区分),
          MktNm(市場区分), MrgnNm(信用区分) など
    """
    if code:
        return _get_paginated("/equities/master", {"code": _normalize_code(code)})
    cache_key = "jquants_equities_master"
    if use_cache:
        cached = get_cached_item(cache_key, ttl_seconds=86400)
        if cached:
            return cached
    rows = _get_paginated("/equities/master")
    if rows:
        set_cached_item(cache_key, rows)
    return rows

def get_daily_bars(code: str, date_from: str = None, date_to: str = None) -> list:
    """1銘柄の日足(調整後OHLCV+売買代金Va+時価総額MktCap)。日付は YYYYMMDD。

    Freeプランでは直近12週分は返らない点に注意。
    """
    params = {"code": _normalize_code(code)}
    if date_from:
        params["from"] = date_from
    if date_to:
        params["to"] = date_to
    return _get_paginated("/equities/bars/daily", params)

def get_daily_bars_by_date(date: str) -> list:
    """指定日の全銘柄日足(クロスセクション)。ユニバース選定・ファクター計算用。"""
    return _get_paginated("/equities/bars/daily", {"date": date})

def get_latest_trading_date() -> str:
    """このプランで取得できる最新の営業日 (YYYY-MM-DD) を返す"""
    bars = get_daily_bars("7203")
    return bars[-1]["Date"] if bars else ""
