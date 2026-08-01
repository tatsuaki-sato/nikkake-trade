import requests
from bs4 import BeautifulSoup

def get_latest_news(ticker: str, limit: int = 3):
    """
    指定したティッカー（例: 7203.T）のYahoo!ファイナンスから最新ニュース見出しを取得する
    """
    # ".T"などを削除して数字コードのみを抽出
    code = ticker.replace('.T', '')
    url = f"https://finance.yahoo.co.jp/quote/{code}.T/news"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    news_list = []
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Yahooファイナンスのニュース見出しを取得
        articles = soup.find_all('a', href=True)
        
        for article in articles:
            href = article['href']
            if '/news/detail/' in href:
                title = article.text.strip()
                # ニュースのタイトルとして短すぎるものは除外
                if title and len(title) > 10:
                    # 重複を防ぐ
                    if not any(title in n for n in news_list):
                        news_list.append(f"・{title}")
                
            if len(news_list) >= limit:
                break
                
    except Exception as e:
        print(f"[{ticker}] ニュース取得中にエラーが発生しました: {e}")
        
    return news_list

if __name__ == "__main__":
    # テスト実行
    print("トヨタ(7203)の最新ニュース:")
    news = get_latest_news("7203.T")
    for n in news:
        print(n)
