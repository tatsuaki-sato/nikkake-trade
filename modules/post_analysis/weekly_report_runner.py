import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.notifier import notify
from common.performance_tracker import generate_weekly_report, db_fallback_occurred

def run_weekly_report():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 週末勝率・成績トラッキング通信送信開始...")
    report_text = generate_weekly_report()
    if db_fallback_occurred():
        report_text = "⚠️ **Supabase接続エラーのためJSON保存にフォールバックしました(Renderの再起動でこの回の分は失われる可能性があります)**\n\n" + report_text
    notify(report_text)

if __name__ == "__main__":
    run_weekly_report()
