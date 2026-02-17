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
    """10bot の日次サマリーレポートを生成する（総資産表示版）。"""
    from src.data_collector import fetch_current_prices, fetch_usd_jpy_rate
    from src.database import get_positions
    from src.config import USD_JPY_RATE

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # 全通貨の現在価格を取得 (USD建て)
    current_prices = fetch_current_prices()

    # 現在のドル円レートを取得
    current_usd_jpy = fetch_usd_jpy_rate()
    
    # 価格が取れなかった場合のフォールバック（ログ出しつつエラーにはしない）
    if not current_prices:
        logger.warning("現在価格の取得に失敗しました。評価額は0として計算されます。")

    lines = [
        "📊 仮想通貨Bot 日次レポート",
        f"📅 {date_str}",
        f"💱 Rate: ¥{current_usd_jpy:.2f}/USD",
        "=" * 28,
    ]

    total_initial = INITIAL_BALANCE * len(BOT_NAMES)  # 全Botの初期投資額合計
    total_current_asset = 0  # 全Botの現在総資産合計
    active_count = 0

    for bot_name in BOT_NAMES:
        summary = get_daily_summary(bot_name, date_str)
        state = get_bot_state(bot_name)
        
        # 1. 現金残高
        cash_balance = state["balance"] if state else INITIAL_BALANCE
        is_active = state["is_active"] if state else True

        # 2. 保有仮想通貨の評価額 (円)
        positions = get_positions(bot_name)
        crypto_value_jpy = 0.0
        
        for symbol, data in positions.items():
            qty = data["position"]
            if qty > 0 and symbol in current_prices:
                price_usd = current_prices[symbol]["price"]
                # 数量 * USD価格 * ドル円レート (リアルタイム)
                value = qty * price_usd * current_usd_jpy
                crypto_value_jpy += value

        # 3. 総資産 = 現金 + 評価額
        bot_total_asset = cash_balance + crypto_value_jpy
        
        # 4. 損益 (PnL) = 総資産 - 初期投資額
        pnl = bot_total_asset - INITIAL_BALANCE
        pnl_pct = (pnl / INITIAL_BALANCE) * 100
        
        total_current_asset += bot_total_asset

        status = "🟢" if is_active else "🔴"
        if pnl > 0:
            pnl_icon = "📈"
        elif pnl < 0:
            pnl_icon = "📉"
        else:
            pnl_icon = "➖"

        bot_num = bot_name.split("_")[0]
        # 表示: Bot番号 アイコン 総資産(円) (損益%)
        lines.append(
            f"{status} #{bot_num} {pnl_icon} ¥{bot_total_asset:,.0f} "
            f"({pnl_pct:+.1f}%) T:{summary['trade_count']}"
        )

        if is_active:
            active_count += 1

    # 全体合計
    total_pnl = total_current_asset - total_initial
    total_pnl_pct = (total_pnl / total_initial) * 100

    lines.extend([
        "=" * 28,
        f"💰 総資産: ¥{total_current_asset:,.0f}",
        f"📈 総PnL: ¥{total_pnl:,.0f} ({total_pnl_pct:+.1f}%)",
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
