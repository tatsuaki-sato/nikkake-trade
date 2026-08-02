import json
import os
import time

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache.json")

def load_cache() -> dict:
    """
    キャッシュファイル（data/cache.json）の読み込み
    """
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"キャッシュ読み込みエラー: {e}")
        return {}

def save_cache(cache_data: dict):
    """
    キャッシュファイル（data/cache.json）の保存
    """
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"キャッシュ保存エラー: {e}")

def get_cached_item(key: str, ttl_seconds: int = 86400):
    """
    キーを指定して有効期間（TTL）内のキャッシュを取得
    超えているか存在しない場合は None を返す
    """
    cache = load_cache()
    item = cache.get(key)
    if not item:
        return None
    
    timestamp = item.get("timestamp", 0)
    if time.time() - timestamp > ttl_seconds:
        return None # 有効期限切れ
        
    return item.get("value")

def set_cached_item(key: str, value):
    """
    キーと値をタイムスタンプ付きで保存
    """
    cache = load_cache()
    cache[key] = {
        "timestamp": time.time(),
        "value": value
    }
    save_cache(cache)
