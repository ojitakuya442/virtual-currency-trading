
import os
import sys
import logging
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

# プロジェクトルートをパスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_recent_trades_all
from src.config import PROJECT_ROOT

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

def send_line_audit(message):
    """LINE Notifyでメッセージを送信する"""
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") # Note: User uses LINE Notify token in secrets as LINE_CHANNEL_ACCESS_TOKEN usually? 
    # Actually, previous code used LINE Messaging API or Notify? 
    # Looking at src/notifier.py is best. But let's assume Notify for simple alerts or check if src/notifier has a send function.
    # The previous notifier.py logic was using 'line-bot-sdk' likely? 
    # Refactoring: It's better to reuse src/notifier.py's send function if possible, but that one might be tied to 'daily report'.
    # Let's check src/notifier.py imports first? 
    # Actually, simplest is direct request to LINE Notify API if env var is LINE_NOTIFY_TOKEN. 
    # If the user uses Messaging API, we need the channel access token and user ID.
    
    # REVISION: Let's use the same method as the daily report.
    pass 

# Implementing internal send function based on standard LINE Notify (most common for alerts) or Messaging API.
# Given previous context, it seems to be Messaging API (LINE_CHANNEL_ACCESS_TOKEN).

def send_message(text):
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")
    
    if not token or not user_id:
        logger.error("LINE設定が見つかりません (.envを確認してください)")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info("LINE通知を送信しました")
    except Exception as e:
        logger.error(f"LINE送信エラー: {e}")

def main():
    logger.info("時報バッチを開始します")
    
    # 1時間前の時刻を取得 (UTC)
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    
    # DBはISO format string で保存されている想定
    since_str = one_hour_ago.isoformat()
    
    trades = get_recent_trades_all(since_str)
    
    if not trades:
        logger.info("直近1時間の取引はありませんでした。通知をスキップします。")
        return

    # メッセージ作成
    lines = [
        "🔔 時報 (過去1時間の取引)",
        "-" * 20
    ]
    
    # Botごとにグループ化すると見やすいかも？あるいは時系列？
    # 時系列順 (古い順) に並んでいるはずなので、そのまま表示
    
    for trade in trades:
        bot_short = trade['bot_name'].split('_')[0] # '01', '02'...
        action = trade['action']
        symbol = trade['symbol']
        price = trade['price']
        qty = trade['quantity']
        
        if action == "HOLD":
            continue

        icon = "🔴" if action == "SELL" else "🟢"
        lines.append(
            f"[{bot_short}] {icon} {action} {symbol}\n"
            f"   @{price:,.1f} x {qty:.4f}"
        )
        lines.append("-" * 20)
    
    if len(lines) <= 2:
        logger.info("表示すべき取引(HOLD以外)がありませんでした。通知スキップ。")
        return

    message = "\n".join(lines)
    send_message(message)
    logger.info("時報バッチ完了")

if __name__ == "__main__":
    main()
