import requests
from bs4 import BeautifulSoup
from common.cache_manager import get_cached_item, set_cached_item

def check_edinet_large_holdings(ticker: str) -> dict:
    """
    金融庁EDINET / TDnet等から「大量保有報告書 (5%ルール)」や「重要自社株買い開示」を検知。
    キャッシュ有効期間: 24時間
    """
    symbol = ticker.replace('.T', '')
    cache_key = f"edinet_{symbol}"
    cached = get_cached_item(cache_key, ttl_seconds=86400)
    if cached:
        return cached

    result = {
        "has_5percent_report": False,
        "details": ""
    }
    
    try:
        # 株探の適時開示・IRページ
        url = f"https://kabutan.jp/stock/news?code={symbol}&nmode=2" # 2: 開示情報
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        news_table = soup.find('table', class_='s_news_list')
        if news_table:
            rows = news_table.find_all('tr')
            for row in rows[1:6]:
                text = row.text.strip()
                if "大量保有" in text or "変更報告書" in text:
                    result["has_5percent_report"] = True
                    result["details"] = "大量保有報告書(5%ルール)の開示あり"
                    break
                elif "自己株式取得" in text or "自社株買い" in text:
                    result["has_5percent_report"] = True
                    result["details"] = "大規模な自社株買い開示あり"
                    break
                    
        set_cached_item(cache_key, result)
    except Exception as e:
        print(f"EDINET開示チェックエラー ({ticker}): {e}")

    return result
