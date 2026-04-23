"""
仮想通貨自動売買Bot - Discord通知モジュール (10bot対応)
Discord Webhook でレポート / アラートを送信する。
"""
import logging
import requests
from datetime import datetime, timezone

from src.config import (
    DISCORD_WEBHOOK_URL,
    BOT_NAMES, INITIAL_BALANCE,
)
from src.database import get_daily_summary, get_bot_state

logger = logging.getLogger(__name__)

# Discord の content フィールド上限 (2000字)
DISCORD_CONTENT_LIMIT = 2000


def send_discord_message(content: str, embeds: list = None) -> bool:
    """Discord Webhook でメッセージを送信する。"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL が設定されていません。送信スキップ。")
        return False

    # content が長すぎる場合は切り詰め
    if content and len(content) > DISCORD_CONTENT_LIMIT:
        content = content[: DISCORD_CONTENT_LIMIT - 20] + "\n…(truncated)"

    # 将来的に他botも同じチャンネルへ投げる前提で、送信元を明示する
    payload = {
        "content": content or "",
        "username": "💹 Crypto Trading Bot",
    }
    if embeds:
        payload["embeds"] = embeds

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if 200 <= resp.status_code < 300:
            logger.info(f"Discord通知送信完了 ({resp.status_code})")
            return True
        logger.error(f"Discord送信エラー: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Discord通知例外: {e}")
        return False


def generate_daily_report() -> str:
    """10bot の日次サマリーレポートを生成する（総資産表示版）。"""
    from src.data_collector import fetch_current_prices, fetch_usd_jpy_rate
    from src.database import get_positions
    from src.config import FIXED_USD_JPY_RATE

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    current_prices = fetch_current_prices()
    current_usd_jpy = fetch_usd_jpy_rate()

    if not current_prices:
        logger.warning("現在価格の取得に失敗しました。評価額は0として計算されます。")

    lines = [
        "📊 **仮想通貨Bot 日次レポート**",
        f"📅 {date_str}",
        f"💱 Real ¥{current_usd_jpy:.2f} / Fixed ¥{FIXED_USD_JPY_RATE:.2f} /USD",
        "─" * 20,
    ]

    total_initial = INITIAL_BALANCE * len(BOT_NAMES)
    total_current_asset_real = 0
    total_asset_fixed = 0
    active_count = 0

    for bot_name in BOT_NAMES:
        summary = get_daily_summary(bot_name, date_str)
        state = get_bot_state(bot_name)

        cash_balance = state["balance"] if state else INITIAL_BALANCE
        is_active = state["is_active"] if state else True

        positions = get_positions(bot_name)
        crypto_value_real = 0.0
        crypto_value_fixed = 0.0
        for symbol, data in positions.items():
            qty = data["position"]
            if qty > 0 and symbol in current_prices:
                price_usd = current_prices[symbol]["price"]
                crypto_value_real += qty * price_usd * current_usd_jpy
                crypto_value_fixed += qty * price_usd * FIXED_USD_JPY_RATE

        bot_total_real = cash_balance + crypto_value_real
        bot_total_fixed = cash_balance + crypto_value_fixed
        pnl = bot_total_fixed - INITIAL_BALANCE
        pnl_pct = (pnl / INITIAL_BALANCE) * 100

        total_current_asset_real += bot_total_real
        total_asset_fixed += bot_total_fixed

        status = "🟢" if is_active else "🔴"
        pnl_icon = "📈" if pnl > 0 else ("📉" if pnl < 0 else "➖")

        bot_num = bot_name.split("_")[0]
        lines.append(
            f"{status} #{bot_num} {pnl_icon} ¥{bot_total_fixed:,.0f} "
            f"({pnl_pct:+.1f}%) T:{summary['trade_count']}"
        )

        if is_active:
            active_count += 1

    total_pnl = total_asset_fixed - total_initial
    total_pnl_pct = (total_pnl / total_initial) * 100

    lines.extend([
        "─" * 20,
        f"💰 総資産(固定): ¥{total_asset_fixed:,.0f}",
        f"   (実勢): ¥{total_current_asset_real:,.0f}",
        f"📈 総PnL: ¥{total_pnl:,.0f} ({total_pnl_pct:+.1f}%)",
        f"🤖 稼働: {active_count}/{len(BOT_NAMES)}",
    ])

    return "\n".join(lines)


def send_daily_report():
    """日次レポートを生成して送信する。"""
    report = generate_daily_report()
    logger.info(f"日次レポート:\n{report}")
    return send_discord_message(report)


def send_error_alert(bot_name: str, error: str):
    """エラー通知を送信する。"""
    message = (
        f"⚠️ **Bot エラー通知**\n"
        f"Bot: `{bot_name}`\n"
        f"エラー: `{error[:500]}`\n"
        f"時刻: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    return send_discord_message(message)
