import requests
from bs4 import BeautifulSoup
import urllib.parse
import yfinance as yf
import time

def get_x_sentiment_score(keyword: str) -> int:
    """
    Yahoo!リアルタイム検索（旧Twitter）をスクレイピングして、話題度（0〜100）を算出
    """
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
    """
    株探（Kabutan）から、指定銘柄の最新ニュースをスクレイピング
    """
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

def get_stock_financial_perks(ticker: str) -> dict:
    """
    銘柄の配当利回り（%）および株主優待情報を取得
    """
    symbol = ticker.replace('.T', '')
    res = {
        "dividend_yield": "データなし",
        "yutai_info": "なし"
    }
    
    # 1. 配当利回りを yfinance または Yahooファイナンスから取得
    try:
        t = yf.Ticker(ticker)
        dy = t.info.get('dividendYield', None)
        if dy is not None:
            res['dividend_yield'] = f"{dy * 100:.2f}%"
        else:
            # 代替: Yahooファイナンス Japan
            yf_url = f"https://finance.yahoo.co.jp/quote/{symbol}.T"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(yf_url, headers=headers, timeout=4)
            if "配当利回り" in resp.text:
                # 簡易抽出
                res['dividend_yield'] = "予想あり"
    except Exception:
        pass
        
    # 2. 株主優待情報（株探）
    try:
        url = f"https://kabutan.jp/stock/yutai?code={symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        yutai_box = soup.find('div', class_='yutai_content') or soup.find('table', class_='fin_year_table')
        if yutai_box:
            text = yutai_box.text.strip().replace('\n', ' ')
            res['yutai_info'] = text[:60] + "..." if len(text) > 60 else text
        elif "優待" in resp.text:
            res['yutai_info'] = "株主優待制度あり (詳細は株探参照)"
    except Exception:
        pass

    return res

def get_market_trending_themes() -> list:
    """
    株探の人気テーマランキングと、各テーマの関連代表銘柄（コード・銘柄名）を取得
    """
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
            for row in rows[1:6]: # 上位5テーマ
                cols = row.find_all('td')
                if len(cols) >= 2:
                    theme_name = cols[1].text.strip()
                    theme_link = cols[1].find('a')['href'] if cols[1].find('a') else None
                    
                    related_stocks = []
                    # テーマ詳細ページから関連銘柄を取得
                    if theme_link:
                        try:
                            t_url = "https://kabutan.jp" + theme_link if not theme_link.startswith('http') else theme_link
                            t_resp = requests.get(t_url, headers=headers, timeout=3)
                            t_soup = BeautifulSoup(t_resp.text, 'html.parser')
                            stk_table = t_soup.find('table', class_='market_table')
                            if stk_table:
                                s_rows = stk_table.find_all('tr')
                                for s_row in s_rows[1:4]: # 上位3関連銘柄
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

if __name__ == "__main__":
    print("X Sentiment (トヨタ):", get_x_sentiment_score("トヨタ"))
    print("Financial Perks (7203.T):", get_stock_financial_perks("7203.T"))
    print("Market Trending Themes with Stocks:", get_market_trending_themes())
