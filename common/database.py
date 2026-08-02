"""
common/database.py
Supabase PostgreSQL によるデータ永続化モジュール
環境変数 DATABASE_URL に接続文字列を設定する
"""
import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    """接続を都度作成して返す（コンテナ再起動でも安全）"""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL 環境変数が設定されていません")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    return conn

def init_db():
    """
    テーブルが存在しない場合のみ自動作成（サーバー起動時に呼び出す）
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # AI推奨シグナル履歴テーブル
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # リアル購入ポートフォリオテーブル
    cur.execute("""
        CREATE TABLE IF NOT EXISTS real_portfolio (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    cur.close()
    conn.close()
    print("✅ Supabase DB テーブル初期化完了")

# ─── Signal History CRUD ───────────────────────────────────────────────────

def db_load_history() -> list:
    """全シグナル履歴をリストで返す（created_at 昇順）"""
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM signal_history ORDER BY created_at ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [row["data"] for row in rows]
    except Exception as e:
        print(f"db_load_history error: {e}")
        return []

def db_save_history(history: list):
    """
    シグナル履歴リストを全件 upsert（INSERT or UPDATE）
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        # まず全件削除してから再挿入（シンプルで確実）
        cur.execute("DELETE FROM signal_history")
        for item in history:
            item_id = item.get("id") or f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            cur.execute(
                "INSERT INTO signal_history (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                (item_id, json.dumps(item, ensure_ascii=False))
            )
        cur.close()
        conn.close()
    except Exception as e:
        print(f"db_save_history error: {e}")

def db_add_signal(item: dict):
    """新しいシグナルを1件追加"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        item_id = item.get("id") or f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        cur.execute(
            "INSERT INTO signal_history (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
            (item_id, json.dumps(item, ensure_ascii=False))
        )
        cur.close()
        conn.close()
    except Exception as e:
        print(f"db_add_signal error: {e}")

def db_delete_signal(signal_id: str) -> bool:
    """IDでシグナルを削除。成功すればTrue"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM signal_history WHERE id = %s", (signal_id,))
        deleted = cur.rowcount > 0
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        print(f"db_delete_signal error: {e}")
        return False

# ─── Real Portfolio CRUD ────────────────────────────────────────────────────

def db_load_portfolio() -> list:
    """全ポートフォリオをリストで返す（created_at 昇順）"""
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT data FROM real_portfolio ORDER BY created_at ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [row["data"] for row in rows]
    except Exception as e:
        print(f"db_load_portfolio error: {e}")
        return []

def db_save_portfolio(portfolio: list):
    """ポートフォリオ全件を upsert"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM real_portfolio")
        for item in portfolio:
            item_id = item.get("id") or f"real_auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            cur.execute(
                "INSERT INTO real_portfolio (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                (item_id, json.dumps(item, ensure_ascii=False))
            )
        cur.close()
        conn.close()
    except Exception as e:
        print(f"db_save_portfolio error: {e}")

def db_add_portfolio_item(item: dict):
    """新しいポートフォリオ銘柄を1件追加"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        item_id = item.get("id") or f"real_auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        cur.execute(
            "INSERT INTO real_portfolio (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
            (item_id, json.dumps(item, ensure_ascii=False))
        )
        cur.close()
        conn.close()
    except Exception as e:
        print(f"db_add_portfolio_item error: {e}")

def db_delete_portfolio_item(item_id: str) -> bool:
    """IDでポートフォリオ銘柄を削除。成功すればTrue"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM real_portfolio WHERE id = %s", (item_id,))
        deleted = cur.rowcount > 0
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        print(f"db_delete_portfolio_item error: {e}")
        return False

def db_update_item_data(table: str, item_id: str, data: dict):
    """特定IDのデータをまるごと更新"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {table} SET data = %s WHERE id = %s",
            (json.dumps(data, ensure_ascii=False), item_id)
        )
        cur.close()
        conn.close()
    except Exception as e:
        print(f"db_update_item_data error ({table}): {e}")
