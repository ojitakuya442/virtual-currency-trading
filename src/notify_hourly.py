"""過去1時間の取引を Discord に embed で通知する時報バッチ。"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone

# プロジェクトルートをパスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_recent_trades_all
from src.notifier import send_trade_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("時報バッチを開始します")

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    trades = get_recent_trades_all(one_hour_ago.isoformat())

    # HOLD以外の取引だけ抽出
    effective = [t for t in trades if t["action"] != "HOLD"]

    if not effective:
        logger.info("直近1時間の取引はありませんでした。通知をスキップします。")
        return

    sent = send_trade_alert(effective)
    if sent:
        logger.info(f"時報バッチ完了 ({len(effective)}件通知)")
    else:
        logger.info("時報バッチ完了 (送信スキップ or 失敗)")


if __name__ == "__main__":
    main()
