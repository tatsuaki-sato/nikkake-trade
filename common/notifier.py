import requests
import json
import time
import os

def send_discord_notification(message: str):
    """
    Discordへの通知（後方互換用 / フォールバック用）
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        # デフォルトのWebhook URL（ローカルテスト用）
        webhook_url = "https://discord.com/api/webhooks/1532994482772115577/WlKy612PVXUO5tsCt5UA8xTuti1QyQHPN70zmWEHPt9snSF7GvsE6Mw4mUSRWuwe5Dhj"
        
    headers = {'Content-Type': 'application/json'}
    chunk_size = 1900
    chunks = [message[i:i+chunk_size] for i in range(0, len(message), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        payload = {'content': chunk}
        try:
            requests.post(webhook_url, headers=headers, data=json.dumps(payload))
        except Exception:
            pass
        if len(chunks) > 1:
            time.sleep(1)

def send_line_notification(message: str):
    """
    LINE Messaging APIへの通知
    GitHub Secretsからトークンを取得して送信します。
    """
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.environ.get("LINE_USER_ID")
    
    if not line_token or not line_user_id:
        print("※LINEのトークンが設定されていないため、Discordへフォールバックします。")
        send_discord_notification(message)
        return
        
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {line_token}"
    }
    
    # LINEのテキストは最大5000文字ですが、念のため2000文字で分割
    chunk_size = 2000
    chunks = [message[i:i+chunk_size] for i in range(0, len(message), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        payload = {
            "to": line_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": chunk
                }
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                print(f"=> LINEへレポートを送信しました！ ({i+1}/{len(chunks)})")
            else:
                print(f"=> LINEへの送信に失敗しました（ステータスコード: {response.status_code}）")
                print(response.text)
        except Exception as e:
            print(f"=> LINE通知エラー: {e}")
            
        if len(chunks) > 1:
            time.sleep(1)

# モジュール群から呼び出されるメインの通知関数
def notify(message: str):
    # LINEトークンがあればLINEへ、なければDiscordへ送信
    send_line_notification(message)
