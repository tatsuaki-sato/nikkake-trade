import re
import requests
from bs4 import BeautifulSoup
import urllib.parse
import yfinance as yf
import time

def get_x_sentiment_score(keyword: str) -> int:
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://search.yahoo.co.jp/realtime/search?p={encoded_keyword}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        tweets = soup.find_all('div', class_='Tweet_body__o3Zjc')
        tweet_count = len(tweets)
        score = min(tweet_count * 10, 100)
        if score == 0:
            score = 50
        return score
    except Exception as e:
        print(f"Xセンチメント取得エラー: {e}")
        return 50

def get_kabutan_news(ticker: str) -> list:
    url = f"https://kabutan.jp/stock/news?code={ticker.replace('.T', '')}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    news_list = []
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        news_table = soup.find('table', class_='s_news_list')
        if news_table:
            rows = news_table.find_all('tr')
            for row in rows[1:4]:
                a_tag = row.find('a')
                if a_tag:
                    news_list.append(a_tag.text.strip())
        return news_list
    except Exception as e:
        print(f"株探ニュース取得エラー: {e}")
        return []

def get_stock_financial_perks(ticker: str, close_price: float = 0.0) -> dict:
    """
    売買判断8大メトリクス（最低購入金額、配当、優待、PER、PBR、EPS成長率）を取得
    """
    symbol = ticker.replace('.T', '')
    res = {
        "min_investment": f"{int(close_price * 100):,}円" if close_price > 0 else "要確認",
        "dividend_yield": "データなし",
        "yutai_info": "なし",
        "per": "データなし",
        "pbr": "データなし",
        "eps_growth": "要確認"
    }
    
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        dy = info.get('dividendYield', None)
        if dy is not None:
            res['dividend_yield'] = f"{dy * 100:.2f}%"
            
        per = info.get('trailingPE', info.get('forwardPE', None))
        if per is not None:
            res['per'] = f"{per:.1f}倍"
            
        pbr = info.get('priceToBook', None)
        if pbr is not None:
            res['pbr'] = f"{pbr:.2f}倍"

        # EPS成長率（来期予想EPS vs 今期実績EPS）
        trailing_eps = info.get('trailingEps', None)
        forward_eps = info.get('forwardEps', None)
        if trailing_eps and forward_eps and trailing_eps > 0:
            growth = ((forward_eps / trailing_eps) - 1) * 100
            prefix = "+" if growth > 0 else ""
            res['eps_growth'] = f"{prefix}{growth:.1f}% (増益予想)" if growth > 0 else f"{growth:.1f}% (減益予想)"
        elif info.get('earningsGrowth', None) is not None:
            eg = info.get('earningsGrowth') * 100
            prefix = "+" if eg > 0 else ""
            res['eps_growth'] = f"{prefix}{eg:.1f}%"
    except Exception:
        pass
        
    try:
        # ページ本文のクラス構造は変わりやすいので、og:descriptionメタタグの
        # 定型文("株主優待に「XX」を実施しています。YY株保有から...")を正規表現で判定する。
        # 優待制度がない銘柄はこの定型文自体が出ず、汎用の会社概要文になる。
        url = f"https://kabutan.jp/stock/yutai?code={symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(resp.text, 'html.parser')

        og_desc_tag = soup.find('meta', attrs={'property': 'og:description'})
        og_desc = og_desc_tag.get('content', '') if og_desc_tag else ''

        m = re.search(r'株主優待に「(.+?)」を実施しています。(\d+)株保有から優待がもらえます。(?:権利確定月は(.+?)です。)?', og_desc)
        if m:
            perk, min_shares, rights_month = m.group(1), m.group(2), m.group(3)
            info_text = f"{perk}({min_shares}株〜)"
            if rights_month:
                info_text += f" 権利確定:{rights_month}"
            res['yutai_info'] = info_text[:60] + "..." if len(info_text) > 60 else info_text
        else:
            res['yutai_info'] = "なし"
    except Exception:
        pass

    return res

# 株探の実在ランキング (mode, 時価総額フィルタ, 表示名)。
# 旧実装の kabutan.jp/theme/ は404で、常にフォールバック固定リストが返っていた。
_KABUTAN_RANKINGS = [
    ("2_9", -1, "本日の活況銘柄(約定回数上位)"),
    ("11_17", 5, "過去1ヶ月上昇率(時価総額1000億円以上)"),
    ("3_3", 5, "年初来高値を更新(時価総額1000億円以上)"),
]

_MARKET_LABEL_RE = re.compile(r'^(東|名|札|福)[ＰＳＧＭ]$')

def _scrape_kabutan_ranking(mode: str, capitalization: int, top_n: int = 3) -> list:
    """株探ランキング1ページから上位銘柄を「銘柄名(コード)」形式で返す(東証プライム限定)"""
    url = f"https://kabutan.jp/warning/?mode={mode}&market=1&capitalization={capitalization}&dispmode=normal"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(url, headers=headers, timeout=8)
    soup = BeautifulSoup(response.text, 'html.parser')
    table = soup.find('table', class_='stock_table')
    stocks = []
    if not table:
        return stocks
    for row in table.find_all('tr')[1:]:
        cells = row.find_all(['th', 'td'])
        if len(cells) < 2:
            continue
        code = cells[0].text.strip()
        if not re.fullmatch(r'\d{4}', code):
            continue
        name = ""
        for cell in cells[1:4]:
            txt = cell.text.strip()
            if txt and not _MARKET_LABEL_RE.match(txt):
                name = txt
                break
        stocks.append(f"{name}({code})" if name else f"({code})")
        if len(stocks) >= top_n:
            break
    return stocks

def get_market_trending_themes() -> tuple:
    """市場で実際に動いている銘柄グループを株探ランキングから取得。

    戻り値は (theme_details, is_fallback)。is_fallback=True のときは全ランキングの
    取得に失敗しており、theme_details は市場実勢を反映しない固定リスト。
    呼び出し側はその場合シグナル登録をスキップし、通知にその旨を明示すること。
    """
    theme_details = []
    for mode, cap, label in _KABUTAN_RANKINGS:
        try:
            stocks = _scrape_kabutan_ranking(mode, cap)
            if stocks:
                theme_details.append({"theme": label, "stocks": stocks})
            time.sleep(1)
        except Exception as e:
            print(f"株探ランキング取得エラー ({label}): {e}")

    if theme_details:
        return theme_details, False

    # 全ランキング取得失敗時のみ: 市場実勢を反映しない静的リスト
    fallback = [
        {"theme": "半導体", "stocks": ["東京エレクトロン(8035)", "レーザーテック(6920)", "アドバンテスト(6857)"]},
        {"theme": "AI・データセンター", "stocks": ["ソフトバンクG(9984)", "富士通(6702)", "NEC(6701)"]},
        {"theme": "高配当・自社株買い", "stocks": ["トヨタ(7203)", "三菱UFJ(8306)", "NTT(9432)"]},
        {"theme": "インバウンド", "stocks": ["三越伊勢丹(3099)", "オリエンタルランド(4661)", "JR東海(9022)"]},
        {"theme": "防衛", "stocks": ["三菱重工(7011)", "川崎重工(7012)", "IHI(7013)"]}
    ]
    return fallback, True
