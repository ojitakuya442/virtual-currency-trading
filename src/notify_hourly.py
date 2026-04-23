"""過去1時間の取引を Discord に通知する時報バッチ。"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone

# プロジェクトルートをパスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_recent_trades_all
from src.notifier import send_discord_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("時報バッチを開始します")

    # 直近1時間の取引を取得
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    trades = get_recent_trades_all(one_hour_ago.isoformat())

    # HOLD以外の取引だけ抽出
    effective = [t for t in trades if t["action"] != "HOLD"]

    if not effective:
        logger.info("直近1時間の取引はありませんでした。通知をスキップします。")
        return

    lines = [
        f"🔔 **時報** (過去1時間の取引: {len(effective)}件)",
        "─" * 20,
    ]

    for trade in effective:
        bot_short = trade["bot_name"].split("_")[0]
        action = trade["action"]
        symbol = trade["symbol"]
        price = trade["price"]
        qty = trade["quantity"]
        pl = trade.get("profit_loss") or 0

        icon = "🔴" if action == "SELL" else "🟢"
        pl_str = f" PL:{pl:+.0f}" if action == "SELL" and pl else ""
        lines.append(
            f"[{bot_short}] {icon} {action} {symbol} @¥{price:,.0f} x {qty:.4f}{pl_str}"
        )

    send_discord_message("\n".join(lines))
    logger.info("時報バッチ完了")


if __name__ == "__main__":
    main()
