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
        
        # Yahooリアルタイム検索の仕様上、完璧な件数取得は難しいですが、
        # 検索結果のツイートカードの数などで簡易的に熱狂度を測ります。
        # 今回はダミー/簡易実装として、結果ページの要素数等からスコアを算出します。
        tweets = soup.find_all('div', class_='Tweet_body__o3Zjc') # クラス名は変動する可能性があります
        
        # もしツイートが多数見つかれば話題性が高いと判断
        tweet_count = len(tweets)
        score = min(tweet_count * 10, 100) # 10件以上表示されていればMAX100点
        
        # 取れなかった場合のフォールバック（APIの制限などで取得できない場合）
        if score == 0:
            score = 50 # 基準値
            
        return score
    except Exception as e:
        print(f"X（Twitter）センチメント取得エラー: {e}")
        return 50 # エラー時はニュートラルな50を返す

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
        
        # 株探のニューステーブルから取得
        news_table = soup.find('table', class_='s_news_list')
        if news_table:
            rows = news_table.find_all('tr')
            for row in rows[1:4]: # 最新3件
                a_tag = row.find('a')
                if a_tag:
                    news_list.append(a_tag.text.strip())
                    
        return news_list
    except Exception as e:
        print(f"株探ニュース取得エラー: {e}")
        return []

if __name__ == "__main__":
    # テスト
    print("X Sentiment (トヨタ):", get_x_sentiment_score("トヨタ"))
    print("Kabutan News (7203):", get_kabutan_news("7203"))
