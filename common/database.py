"""
common/database.py
Supabase Python クライアント（REST API）によるデータ永続化
環境変数:
  SUPABASE_URL  = https://skfkwditegawcgcdblmi.supabase.co
  SUPABASE_KEY  = service_role キー（Settings → API → service_role）
"""
import os
import json
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client = None

def get_client():
    """Supabaseクライアントをシングルトンで返す"""
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 環境変数が設定されていません")
    from supabase import create_client
    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def init_db():
    """接続確認（テーブルはSupabase SQL Editorで作成済み前提）"""
    try:
        sb = get_client()
        sb.table("signal_history").select("id").limit(1).execute()
        sb.table("real_portfolio").select("id").limit(1).execute()
        sb.table("watchlist").select("id").limit(1).execute()
        print("✅ Supabase 接続確認 OK")
    except Exception as e:
        print(f"⚠️ Supabase 接続確認 NG: {e}")

# ─── Signal History CRUD ───────────────────────────────────────────────────

def db_load_history() -> list:
    """全シグナル履歴を created_at 昇順で返す"""
    sb = get_client()
    resp = sb.table("signal_history").select("data").order("created_at", desc=False).execute()
    return [row["data"] for row in (resp.data or [])]

def db_save_history(history: list):
    """シグナル履歴リストを全件 upsert"""
    sb = get_client()
    # 全削除してから再挿入（シンプル＆確実）
    sb.table("signal_history").delete().neq("id", "___never___").execute()
    if history:
        rows = [
            {
                "id": item.get("id") or f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "data": item
            }
            for item in history
        ]
        sb.table("signal_history").upsert(rows).execute()

def db_add_signal(item: dict):
    """新しいシグナルを1件追加"""
    sb = get_client()
    item_id = item.get("id") or f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    sb.table("signal_history").upsert({"id": item_id, "data": item}).execute()

def db_delete_signal(signal_id: str) -> bool:
    """IDでシグナルを削除"""
    sb = get_client()
    resp = sb.table("signal_history").delete().eq("id", signal_id).execute()
    return True

# ─── Watchlist CRUD ─────────────────────────────────────────────────────────

def db_load_watchlist() -> list:
    """ウォッチリスト全件を created_at 昇順で返す"""
    sb = get_client()
    resp = sb.table("watchlist").select("data").order("created_at", desc=False).execute()
    return [row["data"] for row in (resp.data or [])]

def db_save_watchlist(items: list):
    """ウォッチリスト全件を upsert"""
    sb = get_client()
    sb.table("watchlist").delete().neq("id", "___never___").execute()
    if items:
        rows = [{"id": item["ticker"], "data": item} for item in items]
        sb.table("watchlist").upsert(rows).execute()

def db_add_watchlist_item(item: dict):
    """ウォッチリスト銘柄を1件追加"""
    sb = get_client()
    sb.table("watchlist").upsert({"id": item["ticker"], "data": item}).execute()

def db_delete_watchlist_item(ticker: str) -> bool:
    """ティッカーでウォッチリスト銘柄を削除"""
    sb = get_client()
    sb.table("watchlist").delete().eq("id", ticker).execute()
    return True

# ─── Real Portfolio CRUD ────────────────────────────────────────────────────

def db_load_portfolio() -> list:
    """全ポートフォリオを created_at 昇順で返す"""
    sb = get_client()
    resp = sb.table("real_portfolio").select("data").order("created_at", desc=False).execute()
    return [row["data"] for row in (resp.data or [])]

def db_save_portfolio(portfolio: list):
    """ポートフォリオ全件を upsert"""
    sb = get_client()
    sb.table("real_portfolio").delete().neq("id", "___never___").execute()
    if portfolio:
        rows = [
            {
                "id": item.get("id") or f"real_auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "data": item
            }
            for item in portfolio
        ]
        sb.table("real_portfolio").upsert(rows).execute()

def db_add_portfolio_item(item: dict):
    """新しいポートフォリオ銘柄を1件追加"""
    sb = get_client()
    item_id = item.get("id") or f"real_auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    sb.table("real_portfolio").upsert({"id": item_id, "data": item}).execute()

def db_delete_portfolio_item(item_id: str) -> bool:
    """IDでポートフォリオ銘柄を削除"""
    sb = get_client()
    sb.table("real_portfolio").delete().eq("id", item_id).execute()
    return True
