import requests
from bs4 import BeautifulSoup
import urllib.parse
import time

def get_x_sentiment_score(keyword: str) -> int:
    """
    Yahoo!リアルタイム検索（旧Twitter）をスクレイピングして、
    指定したキーワード（銘柄名やコード）の直近の話題度（バズり度）を
    0〜100のスコアで返します。
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
        print(f"X（Twitter）センチメント取得エラー: {e}")
        return 50

def get_kabutan_news(ticker: str) -> list:
    """
    株探（Kabutan）から、指定銘柄の最新ニュースやテーマをスクレイピングします。
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

def get_market_trending_themes() -> list:
    """
    特定銘柄のヒットがない場合に、株探（Kabutan）の「人気テーマランキング」から
    現在市場で最も注目・トレンドになっているテーマを取得します。
    """
    url = "https://kabutan.jp/theme/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    themes = []
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 株探のテーマ人気ランキング
        theme_table = soup.find('table', class_='market_table')
        if theme_table:
            rows = theme_table.find_all('tr')
            for row in rows[1:6]: # 上位5テーマ
                cols = row.find_all('td')
                if len(cols) >= 2:
                    theme_name = cols[1].text.strip()
                    if theme_name:
                        themes.append(theme_name)
        
        # もし取れなかった場合のフォールバック（主要市況ニュースなど）
        if not themes:
            top_news = soup.find_all('a', href=True)
            for a in top_news:
                if '/news/marketnews/' in a['href'] and len(a.text.strip()) > 10:
                    themes.append(a.text.strip())
                    if len(themes) >= 5:
                        break
    except Exception as e:
        print(f"トレンドテーマ取得エラー: {e}")
        
    if not themes:
        themes = ["半導体", "AI・人工知能", "インバウンド", "防衛", "高配当・自社株買い"]
        
    return themes

if __name__ == "__main__":
    print("X Sentiment (トヨタ):", get_x_sentiment_score("トヨタ"))
    print("Kabutan News (7203):", get_kabutan_news("7203"))
    print("Market Trending Themes:", get_market_trending_themes())
