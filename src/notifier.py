"""
仮想通貨自動売買Bot - LINE通知モジュール (10bot対応)
日次サマリーレポートとエラー通知を送信する。
"""
import logging
import requests
from datetime import datetime, timezone

from src.config import (
    LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID,
    BOT_NAMES, INITIAL_BALANCE,
)
from src.database import get_daily_summary, get_bot_state

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"


def send_line_message(message: str):
    """LINEメッセージを送信する。"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        logger.warning("LINE認証情報が設定されていません。送信スキップ。")
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }

    data = {
        "to": LINE_USER_ID,
        "messages": [
            {"type": "text", "text": message[:5000]}  # LINE上限5000文字
        ],
    }

    try:
        resp = requests.post(LINE_API_URL, headers=headers, json=data, timeout=10)
        if resp.status_code == 200:
            logger.info("LINE通知送信完了")
            return True
        else:
            logger.error(f"LINE送信エラー: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"LINE通知例外: {e}")
        return False


def generate_daily_report() -> str:
    """10bot の日次サマリーレポートを生成する。"""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    lines = [
        "📊 仮想通貨Bot 日次レポート",
        f"📅 {date_str}",
        "=" * 28,
    ]

    total_pnl = 0
    total_asset = 0
    active_count = 0

    for bot_name in BOT_NAMES:
        summary = get_daily_summary(bot_name, date_str)
        state = get_bot_state(bot_name)
        balance = state["balance"] if state else INITIAL_BALANCE
        is_active = state["is_active"] if state else 1

        pnl = balance - INITIAL_BALANCE
        pnl_pct = (pnl / INITIAL_BALANCE) * 100
        total_pnl += pnl
        total_asset += balance

        status = "🟢" if is_active else "🔴"
        if pnl > 0:
            pnl_icon = "📈"
        elif pnl < 0:
            pnl_icon = "📉"
        else:
            pnl_icon = "➖"

        bot_num = bot_name.split("_")[0]
        lines.append(
            f"{status} #{bot_num} {pnl_icon} ${balance:,.0f} "
            f"({pnl_pct:+.1f}%) T:{summary['trade_count']}"
        )

        if is_active:
            active_count += 1

    # 合計
    total_pnl_pct = (total_pnl / (INITIAL_BALANCE * len(BOT_NAMES))) * 100
    lines.extend([
        "=" * 28,
        f"💰 合計: ${total_asset:,.0f}",
        f"📈 総PnL: ${total_pnl:,.0f} ({total_pnl_pct:+.1f}%)",
        f"🤖 稼働: {active_count}/{len(BOT_NAMES)}",
    ])

    return "\n".join(lines)


def send_daily_report():
    """日次レポートを生成して送信する。"""
    report = generate_daily_report()
    logger.info(f"日次レポート:\n{report}")
    return send_line_message(report)


def send_error_alert(bot_name: str, error: str):
    """エラー通知を送信する。"""
    message = (
        f"⚠️ Bot エラー通知\n"
        f"Bot: {bot_name}\n"
        f"エラー: {error[:200]}\n"
        f"時刻: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    return send_line_message(message)
