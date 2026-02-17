"""日次レポート送信スクリプト"""
import sys
import logging

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.database import init_database
from src.notifier import send_daily_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    init_database()
    send_daily_report()
