"""
仮想通貨自動売買Bot - メイン実行スクリプト (10bot対応)
5分ごとにGitHub Actionsで実行される。

処理フロー:
  1. 価格データ取得 (現物 + デリバ)
  2. OHLCV取得 → 指標計算
  3. 10bot のシグナル計算 (依存順)
  4. Simulator でポジション調整
  5. スナップショット保存
"""
import sys
import logging
import traceback
from datetime import datetime, timezone

import pandas as pd

# プロジェクトルートをパスに追加
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.config import SYMBOLS, BOT_CONFIGS, BOT_NAMES
from src.database import init_database, save_price, get_recent_prices
from src.data_collector import (
    create_exchange, fetch_ohlcv, fetch_current_prices,
)
from src.indicators import add_core_indicators
from src.simulator import Simulator

# Bot imports
from src.bots.bot_01_donchian import BotDonchian
from src.bots.bot_02_ema_adx import BotEmaAdx
from src.bots.bot_03_bb_zscore import BotBBZscore
from src.bots.bot_04_vwap import BotVWAP
from src.bots.bot_05_squeeze import BotSqueeze
from src.bots.bot_06_vol_momentum import BotVolMomentum
from src.bots.bot_07_pair_trade import BotPairTrade
from src.bots.bot_08_regime import BotRegime
from src.bots.bot_09_ml_gate import BotMLGate
from src.bots.bot_10_deriv import BotDerivatives

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Bot クラス → config名 マッピング
BOT_CLASSES = {
    "01_donchian": BotDonchian,
    "02_ema_adx": BotEmaAdx,
    "03_bb_zscore": BotBBZscore,
    "04_vwap": BotVWAP,
    "05_squeeze": BotSqueeze,
    "06_vol_momentum": BotVolMomentum,
    "07_pair_trade": BotPairTrade,
    "08_regime": BotRegime,
    "09_ml_gate": BotMLGate,
    "10_deriv": BotDerivatives,
}


def main():
    logger.info("=" * 60)
    logger.info("仮想通貨自動売買Bot 起動 (10bot体制)")
    logger.info("=" * 60)

    # DB初期化
    init_database()

    # 取引所接続
    exchange = create_exchange()

    # ── Step 1: 現在価格取得 ──
    logger.info("📊 現在価格を取得中...")
    current_prices = fetch_current_prices(exchange)

    if not current_prices:
        logger.error("価格データの取得に失敗しました。終了します。")
        return

    for symbol, data in current_prices.items():
        logger.info(f"  {symbol}: ${data['price']:,.2f}")

    # ── Step 2: OHLCV取得 + 指標計算 ──
    logger.info("📈 OHLCVデータを取得中...")
    data_dict = {}  # {symbol: DataFrame}

    for symbol in SYMBOLS:
        try:
            df = fetch_ohlcv(exchange, symbol, timeframe="5m", limit=500)
            if df is not None and not df.empty:
                df = add_core_indicators(df)
                data_dict[symbol] = df

                # 最新価格をDBに保存
                last = df.iloc[-1]
                save_price(
                    timestamp=last["timestamp"].isoformat() if hasattr(last["timestamp"], "isoformat") else str(last["timestamp"]),
                    symbol=symbol,
                    open_p=last["open"],
                    high=last["high"],
                    low=last["low"],
                    close=last["close"],
                    volume=last["volume"],
                )
            else:
                logger.warning(f"[{symbol}] OHLCVデータなし")
        except Exception as e:
            logger.error(f"[{symbol}] OHLCV取得エラー: {e}")

    if not data_dict:
        logger.error("OHLCVデータが一切取得できませんでした。終了します。")
        return

    # ── Step 3 & 4: 各Botシグナル計算 → ポジション調整 ──
    logger.info(f"🤖 {len(BOT_NAMES)}bot のシグナルを計算中...")

    results = {}
    for bot_name in BOT_NAMES:
        try:
            bot_config = BOT_CONFIGS[bot_name]
            bot_class = BOT_CLASSES[bot_name]
            bot = bot_class(bot_config)
            sim = Simulator(bot_name)

            # シグナル取得
            signals = bot.get_signals(data_dict)

            # ポジション調整
            bot_results = []
            for symbol, signal in signals.items():
                if symbol in current_prices:
                    price = current_prices[symbol]["price"]
                    result = sim.apply_signal(symbol, signal, price)
                    bot_results.append(result)

                    if result.get("executed"):
                        logger.info(
                            f"  ✅ [{bot_name}] {result['action']} {symbol}: "
                            f"pos {result.get('prev_pos', 0):.2f}→{result.get('target_pos', 0):.2f}"
                        )

            # スナップショット保存
            prices_for_snap = {s: d["price"] for s, d in current_prices.items()}
            sim.save_snapshot(prices_for_snap)

            results[bot_name] = {
                "signals": signals,
                "trades": bot_results,
                "status": "OK",
            }

        except Exception as e:
            logger.error(f"  ❌ [{bot_name}] エラー: {e}")
            logger.debug(traceback.format_exc())
            results[bot_name] = {"status": "ERROR", "error": str(e)}

    # ── Step 5: サマリー出力 ──
    logger.info("=" * 60)
    logger.info("📋 実行サマリー:")
    ok_count = sum(1 for r in results.values() if r["status"] == "OK")
    err_count = sum(1 for r in results.values() if r["status"] == "ERROR")
    trade_count = sum(
        sum(1 for t in r.get("trades", []) if t.get("executed"))
        for r in results.values()
    )
    logger.info(f"  Bot正常: {ok_count}/{len(BOT_NAMES)}, エラー: {err_count}, 約定数: {trade_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
