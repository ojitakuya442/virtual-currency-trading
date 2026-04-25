"""
仮想通貨自動売買Bot - Discord通知モジュール (10bot対応)
Discord Webhook で embed (カード形式) のレポート / アラートを送信する。
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

# Discord 制約
DISCORD_CONTENT_LIMIT = 2000
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_MAX_FIELDS = 25

# embed 色
COLOR_GREEN = 0x2ECC71  # PnL プラス
COLOR_RED = 0xE74C3C    # PnL マイナス
COLOR_BLUE = 0x3498DB   # 中立
COLOR_ORANGE = 0xE67E22  # SELL シグナル多め
COLOR_GRAY = 0x95A5A6   # 通知なし

# 送信元表示
SENDER_USERNAME = "💹 Crypto Trading Bot"

# 各botの短縮名 (embed のフィールド見出し用)
BOT_SHORT_NAMES = {
    "01_donchian": "Donchian",
    "02_ema_adx": "EMA-ADX",
    "03_bb_zscore": "BB Z-Score",
    "04_vwap": "VWAP",
    "05_squeeze": "Squeeze",
    "06_vol_momentum": "Vol Mom",
    "07_pair_trade": "Pair Trade",
    "08_regime": "Regime",
    "09_ml_gate": "ML Gate",
    "10_deriv": "Deriv",
}


def send_discord_message(content: str = "", embeds: list = None) -> bool:
    """Discord Webhook でメッセージを送信する。content/embed どちらか or 両方。"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL が設定されていません。送信スキップ。")
        return False

    if content and len(content) > DISCORD_CONTENT_LIMIT:
        content = content[: DISCORD_CONTENT_LIMIT - 20] + "\n…(truncated)"

    payload = {
        "content": content or "",
        "username": SENDER_USERNAME,
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


# ────────────────────────────────────────────────────────────
#  日次レポート
# ────────────────────────────────────────────────────────────

def _gather_daily_stats() -> dict:
    """日次レポートに必要な統計情報を1辞書にまとめて返す。"""
    from src.data_collector import fetch_current_prices, fetch_usd_jpy_rate
    from src.database import get_positions
    from src.config import FIXED_USD_JPY_RATE

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    current_prices = fetch_current_prices()
    current_usd_jpy = fetch_usd_jpy_rate()

    if not current_prices:
        logger.warning("現在価格の取得に失敗しました。評価額は0として計算されます。")

    bots = []
    total_initial = INITIAL_BALANCE * len(BOT_NAMES)
    total_real = 0.0
    total_fixed = 0.0
    active_count = 0

    for bot_name in BOT_NAMES:
        summary = get_daily_summary(bot_name, date_str)
        state = get_bot_state(bot_name)

        cash_balance = state["balance"] if state else INITIAL_BALANCE
        is_active = bool(state["is_active"]) if state else True

        positions = get_positions(bot_name)
        crypto_real = 0.0
        crypto_fixed = 0.0
        for symbol, data in positions.items():
            qty = data["position"]
            if qty > 0 and symbol in current_prices:
                price_usd = current_prices[symbol]["price"]
                crypto_real += qty * price_usd * current_usd_jpy
                crypto_fixed += qty * price_usd * FIXED_USD_JPY_RATE

        bot_total_fixed = cash_balance + crypto_fixed
        bot_total_real = cash_balance + crypto_real
        pnl = bot_total_fixed - INITIAL_BALANCE
        pnl_pct = (pnl / INITIAL_BALANCE) * 100

        total_real += bot_total_real
        total_fixed += bot_total_fixed
        if is_active:
            active_count += 1

        bots.append({
            "bot_name": bot_name,
            "num": bot_name.split("_")[0],
            "short_name": BOT_SHORT_NAMES.get(bot_name, bot_name),
            "is_active": is_active,
            "balance": cash_balance,
            "crypto_value_fixed": crypto_fixed,
            "total_fixed": bot_total_fixed,
            "total_real": bot_total_real,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "trade_count": summary["trade_count"],
        })

    total_pnl = total_fixed - total_initial
    total_pnl_pct = (total_pnl / total_initial) * 100

    return {
        "now": now,
        "date_str": date_str,
        "usd_jpy_real": current_usd_jpy,
        "usd_jpy_fixed": FIXED_USD_JPY_RATE,
        "bots": bots,
        "total_initial": total_initial,
        "total_real": total_real,
        "total_fixed": total_fixed,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "active_count": active_count,
        "bot_count": len(BOT_NAMES),
    }


def _build_daily_embed(stats: dict) -> dict:
    """日次レポートを Discord embed 形式で構築する。"""
    color = COLOR_GREEN if stats["total_pnl"] > 0 else (
        COLOR_RED if stats["total_pnl"] < 0 else COLOR_BLUE
    )
    pnl_icon = "📈" if stats["total_pnl"] > 0 else ("📉" if stats["total_pnl"] < 0 else "➖")

    description = (
        f"**総資産** ¥{stats['total_fixed']:,.0f}  "
        f"{pnl_icon} **{stats['total_pnl']:+,.0f}** ({stats['total_pnl_pct']:+.2f}%)\n"
        f"実勢評価額 ¥{stats['total_real']:,.0f} / 為替 ¥{stats['usd_jpy_real']:.2f}/USD\n"
        f"🤖 稼働 {stats['active_count']}/{stats['bot_count']} bots"
    )

    fields = []
    for b in stats["bots"]:
        status = "🟢" if b["is_active"] else "🔴"
        bot_pnl_icon = "📈" if b["pnl"] > 0 else ("📉" if b["pnl"] < 0 else "➖")
        # 値はコンパクトに 2行
        value = (
            f"¥{b['total_fixed']:,.0f}\n"
            f"{bot_pnl_icon} {b['pnl_pct']:+.1f}%  T:{b['trade_count']}"
        )
        fields.append({
            "name": f"{status} #{b['num']} {b['short_name']}",
            "value": value,
            "inline": True,
        })

    embed = {
        "title": "📊 仮想通貨Bot 日次レポート",
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": f"📅 {stats['date_str']} | Fixed Rate ¥{stats['usd_jpy_fixed']:.0f}/USD"},
        "timestamp": stats["now"].isoformat(),
    }
    return embed


def send_daily_report():
    """日次レポート (embed) を生成して送信する。"""
    stats = _gather_daily_stats()
    embed = _build_daily_embed(stats)
    logger.info(
        f"日次レポート: 総資産¥{stats['total_fixed']:,.0f} "
        f"PnL{stats['total_pnl']:+,.0f} ({stats['total_pnl_pct']:+.2f}%) "
        f"稼働{stats['active_count']}/{stats['bot_count']}"
    )
    return send_discord_message(embeds=[embed])


# ────────────────────────────────────────────────────────────
#  時報 (取引アラート)
# ────────────────────────────────────────────────────────────

def _build_trade_alert_embed(trades: list) -> dict:
    """過去N時間の取引リストを embed に変換する。"""
    buy_count = sum(1 for t in trades if t["action"] == "BUY")
    sell_count = sum(1 for t in trades if t["action"] == "SELL")

    # 色は SELL 比率で決定
    if sell_count > buy_count:
        color = COLOR_ORANGE  # 利確/損切り多め
    elif buy_count > 0:
        color = COLOR_GREEN
    else:
        color = COLOR_GRAY

    # 取引行を組み立て
    lines = []
    for t in trades:
        bot_short = BOT_SHORT_NAMES.get(t["bot_name"], t["bot_name"].split("_")[0])
        action = t["action"]
        symbol = t["symbol"].replace("/USD", "")  # 表示縮約
        price = t["price"]
        qty = t["quantity"]
        pl = t.get("profit_loss") or 0

        icon = "🟢" if action == "BUY" else "🔴"
        # SELL なら PnL 表示
        if action == "SELL":
            pl_icon = "📈" if pl > 0 else ("📉" if pl < 0 else "")
            pl_str = f"  {pl_icon} ¥{pl:+,.0f}" if pl else ""
            lines.append(
                f"{icon} **#{bot_short}** SELL `{symbol}` {qty:.4f} @¥{price:,.0f}{pl_str}"
            )
        else:
            lines.append(
                f"{icon} **#{bot_short}** BUY `{symbol}` {qty:.4f} @¥{price:,.0f}"
            )

    # 描画上限内に収める (description 4096字)
    description = "\n".join(lines)
    if len(description) > DISCORD_EMBED_DESCRIPTION_LIMIT - 100:
        # 古い順から削って末尾に「+N more」を入れる
        kept = []
        for line in reversed(lines):
            if sum(len(l) + 1 for l in kept) + len(line) > DISCORD_EMBED_DESCRIPTION_LIMIT - 200:
                break
            kept.insert(0, line)
        omitted = len(lines) - len(kept)
        description = "\n".join(kept) + f"\n…他 {omitted} 件省略"

    title = f"🔔 取引アラート ({len(trades)}件)"
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"BUY {buy_count} / SELL {sell_count}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return embed


def send_trade_alert(trades: list) -> bool:
    """過去N時間の取引リストを Discord に通知する。HOLD は除外済み前提。"""
    if not trades:
        logger.info("通知対象の取引なし。送信スキップ。")
        return False
    embed = _build_trade_alert_embed(trades)
    return send_discord_message(embeds=[embed])


# ────────────────────────────────────────────────────────────
#  エラー通知
# ────────────────────────────────────────────────────────────

def send_error_alert(bot_name: str, error: str) -> bool:
    """エラー通知 (赤色 embed) を送信する。"""
    embed = {
        "title": f"⚠️ Bot エラー: {bot_name}",
        "description": f"```\n{error[:1500]}\n```",
        "color": COLOR_RED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return send_discord_message(embeds=[embed])


# ────────────────────────────────────────────────────────────
#  後方互換: テキスト版日次レポート (ログ・デバッグ用)
# ────────────────────────────────────────────────────────────

def generate_daily_report() -> str:
    """テキスト形式の日次レポートを生成する (ログ出力用)。"""
    stats = _gather_daily_stats()
    lines = [
        "📊 仮想通貨Bot 日次レポート",
        f"📅 {stats['date_str']}",
        f"💱 Real ¥{stats['usd_jpy_real']:.2f} / Fixed ¥{stats['usd_jpy_fixed']:.2f} /USD",
        "─" * 20,
    ]
    for b in stats["bots"]:
        status = "🟢" if b["is_active"] else "🔴"
        pnl_icon = "📈" if b["pnl"] > 0 else ("📉" if b["pnl"] < 0 else "➖")
        lines.append(
            f"{status} #{b['num']} {pnl_icon} ¥{b['total_fixed']:,.0f} "
            f"({b['pnl_pct']:+.1f}%) T:{b['trade_count']}"
        )
    lines.extend([
        "─" * 20,
        f"💰 総資産(固定): ¥{stats['total_fixed']:,.0f}",
        f"   (実勢): ¥{stats['total_real']:,.0f}",
        f"📈 総PnL: ¥{stats['total_pnl']:,.0f} ({stats['total_pnl_pct']:+.1f}%)",
        f"🤖 稼働: {stats['active_count']}/{stats['bot_count']}",
    ])
    return "\n".join(lines)
