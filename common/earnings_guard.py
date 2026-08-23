"""
common/earnings_guard.py
決算またぎ抑制(v2設計 Layer 4)。

決算発表の直前は、ファクターやテクニカルがどれだけ良くても発表内容次第で
株価が大きくジャンプする「イベントギャンブル」になる。発表が近い銘柄は
新規シグナルを出さない。

データソースは2段構え:
  1. J-Quants /fins/earnings-date (scheduled_date指定) — 有償プランで最新データが
     取れる場合はこちらが正。Freeプランは12週遅延のため未来の予定が返らず、
     実質的に空になる(その場合は黙って2へ)。
  2. 株探「決算発表予定銘柄」(warning/?mode=5_1) — 遅延なし・無料。
     翌営業日に発表予定の銘柄一覧が取れる。

どちらも取れなかった場合は空集合を返す(= 抑制なし)。ガードの失敗で
スキャン自体を止めないこと。
"""
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from common.cache_manager import get_cached_item, set_cached_item

GUARD_DAYS = 3  # 発表の何日前から新規シグナルを抑制するか(暦日)

_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def _from_jquants(days_ahead: int) -> set:
    """J-Quants から今後 days_ahead 日以内に決算予定のある銘柄コード(4桁)を取得"""
    from common.market_data import jquants_available, _get_paginated
    if not jquants_available():
        return set()
    codes = set()
    today = datetime.now()
    for i in range(days_ahead + 1):
        date = (today + timedelta(days=i)).strftime("%Y%m%d")
        try:
            rows = _get_paginated("/fins/earnings-date", {"scheduled_date": date}, max_pages=2)
            codes.update(r["Code"][:4] for r in rows if r.get("Code"))
        except Exception as e:
            print(f"[earnings_guard] J-Quants取得エラー ({date}): {e}")
            break
    return codes


def _from_kabutan() -> set:
    """株探の決算発表予定ページから、直近発表予定の銘柄コード(4桁)を取得"""
    codes = set()
    try:
        url = "https://kabutan.jp/warning/?mode=5_1&market=0&capitalization=-1&dispmode=normal"
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='stock_table')
        if table:
            for row in table.find_all('tr')[1:]:
                cells = row.find_all(['th', 'td'])
                if cells:
                    code = cells[0].text.strip()
                    if re.fullmatch(r'\d{4}', code):
                        codes.add(code)
        # 複数ページある場合は2ページ目まで(1ページ約15件)
        resp2 = requests.get(url + "&page=2", headers=_HEADERS, timeout=8)
        soup2 = BeautifulSoup(resp2.text, 'html.parser')
        table2 = soup2.find('table', class_='stock_table')
        if table2:
            for row in table2.find_all('tr')[1:]:
                cells = row.find_all(['th', 'td'])
                if cells:
                    code = cells[0].text.strip()
                    if re.fullmatch(r'\d{4}', code):
                        codes.add(code)
    except Exception as e:
        print(f"[earnings_guard] 株探取得エラー: {e}")
    return codes


def get_upcoming_earnings_codes(days_ahead: int = GUARD_DAYS) -> set:
    """今後 days_ahead 日以内に決算発表予定のある銘柄コード(4桁文字列)の集合。6hキャッシュ。"""
    cache_key = f"earnings_guard_{days_ahead}"
    cached = get_cached_item(cache_key, ttl_seconds=6 * 3600)
    if cached is not None:
        return set(cached)

    codes = _from_jquants(days_ahead)
    source = "J-Quants"
    if not codes:
        codes = _from_kabutan()
        source = "株探"
    print(f"[earnings_guard] 決算接近銘柄: {len(codes)}件 (ソース: {source if codes else 'なし'})")

    set_cached_item(cache_key, sorted(codes))
    return codes


def is_earnings_imminent(ticker: str, upcoming_codes: set = None) -> bool:
    """ticker("7203.T"/"7203")が決算発表直前かどうか"""
    if upcoming_codes is None:
        upcoming_codes = get_upcoming_earnings_codes()
    code = ticker.replace(".T", "").strip()[:4]
    return code in upcoming_codes
