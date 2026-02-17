"""
過去データ一括取得スクリプト
BTC/ETH/SOLの直近1ヶ月分の5分足データを取得し、SQLiteに保存する。
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import SYMBOLS, HISTORICAL_DAYS
from src.data_collector import create_exchange, fetch_historical_data
from src.database import init_database, save_prices_bulk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """全銘柄の過去データを取得する。"""
    logger.info("=" * 60)
    logger.info(f"過去{HISTORICAL_DAYS}日分のヒストリカルデータを取得します")
    logger.info("=" * 60)

    # DB初期化
    init_database()

    # 取引所接続
    exchange = create_exchange()

    total_records = 0
    for symbol in SYMBOLS:
        logger.info(f"\n--- {symbol} ---")
        df = fetch_historical_data(exchange, symbol, days=HISTORICAL_DAYS, timeframe="5m")

        if df is not None and not df.empty:
            save_prices_bulk(df)
            total_records += len(df)
            logger.info(f"[{symbol}] {len(df)}件保存完了")
        else:
            logger.warning(f"[{symbol}] データ取得失敗")

    logger.info(f"\n合計 {total_records}件のデータを保存しました。")
    logger.info("完了!")


if __name__ == "__main__":
    main()
