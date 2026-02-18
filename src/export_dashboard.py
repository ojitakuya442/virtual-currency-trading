
import json
import os
import sys
import logging
from datetime import datetime, timezone, timedelta

# Project root setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_daily_summary, get_bot_state, get_positions, get_recent_trades_all, get_connection
from src.data_collector import fetch_current_prices, fetch_usd_jpy_rate
from src.config import BOT_NAMES, INITIAL_BALANCE, FIXED_USD_JPY_RATE, PROJECT_ROOT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def export_dashboard_data():
    """
    ダッシュボード表示用の全データを集計し、docs/dashboard.json に出力する。
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # 1. マーケットデータ取得
    current_prices = fetch_current_prices()
    current_usd_jpy = fetch_usd_jpy_rate()

    # 2. Botデータ集計
    bots_data = []
    total_initial = 0
    total_asset_fixed = 0
    total_asset_real = 0
    active_count = 0

    for bot_name in BOT_NAMES:
        summary = get_daily_summary(bot_name, date_str)
        state = get_bot_state(bot_name)
        
        # 現金
        cash = state["balance"] if state else INITIAL_BALANCE
        is_active = state["is_active"] if state else True
        if is_active:
            active_count += 1
        
        # ポジション評価
        positions = get_positions(bot_name)
        crypto_val_fixed = 0.0
        crypto_val_real = 0.0
        
        pos_list = []
        for symbol, data in positions.items():
            qty = data["position"]
            if qty > 0:
                price = current_prices.get(symbol, {}).get("price", 0)
                crypto_val_fixed += qty * price * FIXED_USD_JPY_RATE
                crypto_val_real += qty * price * current_usd_jpy
                pos_list.append({
                    "symbol": symbol,
                    "quantity": qty,
                    "price_usd": price,
                    "value_jpy_fixed": qty * price * FIXED_USD_JPY_RATE
                })

        bot_total_fixed = cash + crypto_val_fixed
        bot_total_real = cash + crypto_val_real
        
        total_initial += INITIAL_BALANCE
        total_asset_fixed += bot_total_fixed
        total_asset_real += bot_total_real

        bots_data.append({
            "name": bot_name,
            "display_name": f"#{bot_name.split('_')[0]}",
            "status": "active" if is_active else "stopped",
            "total_jpy_fixed": bot_total_fixed,
            "pnl_jpy": bot_total_fixed - INITIAL_BALANCE,
            "pnl_pct": ((bot_total_fixed - INITIAL_BALANCE) / INITIAL_BALANCE) * 100,
            "trade_count_today": summary["trade_count"],
            "positions": pos_list
        })

    # 3. 直近の取引 (過去24時間)
    since_24h = (now - timedelta(hours=24)).isoformat()
    recent_trades = get_recent_trades_all(since_24h)
    # 整形
    formatted_trades = []
    for t in reversed(recent_trades): # 新しい順
        formatted_trades.append({
            "timestamp": t["timestamp"],
            "bot": t["bot_name"].split("_")[0],
            "action": t["action"],
            "symbol": t["symbol"],
            "price": t["price"],
            "quantity": t["quantity"],
            "icon": "🔴" if t["action"] == "SELL" else "🟢"
        })

    # 4. JSON構築
    dashboard_data = {
        "metadata": {
            "updated_at": now.isoformat(),
            "usd_jpy_real": current_usd_jpy,
            "usd_jpy_fixed": FIXED_USD_JPY_RATE,
        },
        "summary": {
            "total_asset_fixed": total_asset_fixed,
            "total_asset_real": total_asset_real,
            "total_pnl": total_asset_fixed - total_initial,
            "total_pnl_pct": ((total_asset_fixed - total_initial) / total_initial) * 100,
            "active_bots": active_count,
            "total_bots": len(BOT_NAMES)
        },
        "bots": bots_data,
        "recent_trades": formatted_trades[:50] # 最大50件
    }

    # 5. 保存
    output_dir = os.path.join(PROJECT_ROOT, "docs")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "dashboard.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Dashboard data exported to {output_path}")

if __name__ == "__main__":
    export_dashboard_data()
