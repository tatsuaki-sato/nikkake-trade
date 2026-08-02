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
        url = f"https://kabutan.jp/stock/yutai?code={symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        yutai_box = soup.find('div', class_='yutai_content') or soup.find('table', class_='fin_year_table')
        if yutai_box:
            text = yutai_box.text.strip().replace('\n', ' ')
            res['yutai_info'] = text[:50] + "..." if len(text) > 50 else text
        elif "優待" in resp.text:
            res['yutai_info'] = "株主優待制度あり"
    except Exception:
        pass

    return res

def get_market_trending_themes() -> list:
    url = "https://kabutan.jp/theme/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    theme_details = []
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        theme_table = soup.find('table', class_='market_table')
        if theme_table:
            rows = theme_table.find_all('tr')
            for row in rows[1:6]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    theme_name = cols[1].text.strip()
                    theme_link = cols[1].find('a')['href'] if cols[1].find('a') else None
                    
                    related_stocks = []
                    if theme_link:
                        try:
                            t_url = "https://kabutan.jp" + theme_link if not theme_link.startswith('http') else theme_link
                            t_resp = requests.get(t_url, headers=headers, timeout=3)
                            t_soup = BeautifulSoup(t_resp.text, 'html.parser')
                            stk_table = t_soup.find('table', class_='market_table')
                            if stk_table:
                                s_rows = stk_table.find_all('tr')
                                for s_row in s_rows[1:4]:
                                    a_tags = s_row.find_all('a')
                                    if len(a_tags) >= 2:
                                        code = a_tags[0].text.strip()
                                        name = a_tags[1].text.strip()
                                        related_stocks.append(f"{name}({code})")
                        except Exception:
                            pass
                            
                    if not related_stocks:
                        related_stocks = ["主要銘柄一覧は株探参照"]
                        
                    theme_details.append({
                        "theme": theme_name,
                        "stocks": related_stocks
                    })
    except Exception as e:
        print(f"トレンドテーマ詳細取得エラー: {e}")
        
    if not theme_details:
        theme_details = [
            {"theme": "半導体", "stocks": ["東京エレクトロン(8035)", "レーザーテック(6920)", "アドバンテスト(6857)"]},
            {"theme": "AI・データセンター", "stocks": ["ソフトバンクG(9984)", "富士通(6702)", "NEC(6701)"]},
            {"theme": "高配当・自社株買い", "stocks": ["トヨタ(7203)", "三菱UFJ(8306)", "NTT(9432)"]},
            {"theme": "インバウンド", "stocks": ["三越伊勢丹(3099)", "オリエンタルランド(4661)", "JR東海(9022)"]},
            {"theme": "防衛", "stocks": ["三菱重工(7011)", "川崎重工(7012)", "IHI(7013)"]}
        ]
        
    return theme_details
