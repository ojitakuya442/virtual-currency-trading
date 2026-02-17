"""
仮想通貨自動売買Bot - データベースモジュール
10bot・target_position アーキテクチャ対応版
"""
import sqlite3
import logging
from datetime import datetime, timezone

from src.config import DB_PATH, INITIAL_BALANCE, BOT_NAMES

logger = logging.getLogger(__name__)


def get_connection():
    """SQLiteデータベース接続を取得する。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_database():
    """テーブルを初期化する（存在しない場合のみ作成）。"""
    conn = get_connection()
    cursor = conn.cursor()

    # 価格ログテーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            UNIQUE(timestamp, symbol)
        )
    """)

    # 取引ログテーブル (target_position対応)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            target_position REAL DEFAULT 0,
            prev_position REAL DEFAULT 0,
            price REAL NOT NULL,
            effective_price REAL NOT NULL,
            quantity REAL NOT NULL,
            balance REAL NOT NULL,
            position REAL NOT NULL,
            profit_loss REAL DEFAULT 0,
            confidence REAL DEFAULT 0,
            note TEXT DEFAULT ''
        )
    """)

    # 残高スナップショットテーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            balance REAL NOT NULL,
            total_position_value REAL DEFAULT 0,
            total_asset REAL NOT NULL,
            daily_pnl REAL DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            trade_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)

    # ボット状態テーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            bot_name TEXT PRIMARY KEY,
            balance REAL NOT NULL,
            is_active INTEGER DEFAULT 1,
            last_updated TEXT NOT NULL
        )
    """)

    # デリバティブ情報テーブル (Bot #10用)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS derivatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            funding_rate REAL,
            open_interest REAL,
            UNIQUE(timestamp, symbol)
        )
    """)

    conn.commit()

    # 初期状態がなければ挿入 (10bot分)
    for bot_name in BOT_NAMES:
        cursor.execute(
            "SELECT 1 FROM bot_state WHERE bot_name = ?", (bot_name,)
        )
        if cursor.fetchone() is None:
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO bot_state (bot_name, balance, is_active, last_updated) "
                "VALUES (?, ?, 1, ?)",
                (bot_name, INITIAL_BALANCE, now),
            )

    conn.commit()
    conn.close()
    logger.info(f"データベースを初期化しました。({len(BOT_NAMES)} bots)")


# ────────────────────────────────────────────
#  価格データ
# ────────────────────────────────────────────

def save_price(timestamp, symbol, open_p, high, low, close, volume):
    """価格データを1件保存する。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO prices "
            "(timestamp, symbol, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, symbol, open_p, high, low, close, volume),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"価格データ保存エラー: {e}")
    finally:
        conn.close()


def save_prices_bulk(df):
    """DataFrameから価格データを一括保存する。"""
    conn = get_connection()
    try:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO prices "
                "(timestamp, symbol, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                    row["symbol"],
                    row.get("open", 0),
                    row.get("high", 0),
                    row.get("low", 0),
                    row.get("close", 0),
                    row.get("volume", 0),
                ),
            )
        conn.commit()
        logger.info(f"{len(df)}件の価格データを保存しました。")
    except sqlite3.Error as e:
        logger.error(f"価格データ一括保存エラー: {e}")
    finally:
        conn.close()


def get_recent_prices(symbol, limit=100):
    """指定銘柄の直近N件の価格データを取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM prices WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def get_latest_price(symbol):
    """指定銘柄の最新価格を取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM prices WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ────────────────────────────────────────────
#  取引ログ
# ────────────────────────────────────────────

def save_trade(timestamp, bot_name, symbol, action, price, effective_price,
               quantity, balance, position, target_position=0, prev_position=0,
               profit_loss=0, confidence=0, note=""):
    """取引ログを1件保存する。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO trades "
            "(timestamp, bot_name, symbol, action, target_position, prev_position, "
            "price, effective_price, quantity, balance, position, "
            "profit_loss, confidence, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, bot_name, symbol, action, target_position, prev_position,
             price, effective_price, quantity, balance, position,
             profit_loss, confidence, note),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"取引ログ保存エラー: {e}")
    finally:
        conn.close()


# ────────────────────────────────────────────
#  残高スナップショット
# ────────────────────────────────────────────

def save_balance_snapshot(timestamp, bot_name, balance, total_position_value,
                          total_asset, daily_pnl, total_pnl, trade_count, is_active):
    """残高スナップショットを保存する。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO balances "
            "(timestamp, bot_name, balance, total_position_value, total_asset, "
            "daily_pnl, total_pnl, trade_count, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, bot_name, balance, total_position_value, total_asset,
             daily_pnl, total_pnl, trade_count, is_active),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"残高保存エラー: {e}")
    finally:
        conn.close()


# ────────────────────────────────────────────
#  ボット状態
# ────────────────────────────────────────────

def update_bot_state(bot_name, balance, is_active=True):
    """ボットの現在状態を更新する。"""
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE bot_state SET balance = ?, is_active = ?, last_updated = ? "
            "WHERE bot_name = ?",
            (balance, 1 if is_active else 0, now, bot_name),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"ボット状態更新エラー: {e}")
    finally:
        conn.close()


def get_bot_state(bot_name):
    """ボットの現在状態を取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM bot_state WHERE bot_name = ?", (bot_name,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_bot_trades(bot_name, since=None):
    """指定ボットの取引履歴を取得する。"""
    conn = get_connection()
    try:
        if since:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE bot_name = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC",
                (bot_name, since),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM trades WHERE bot_name = ? ORDER BY timestamp ASC",
                (bot_name,),
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_daily_summary(bot_name, date_str):
    """指定ボットの日次サマリーを取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) as trade_count FROM trades "
            "WHERE bot_name = ? AND timestamp LIKE ? AND action != 'HOLD'",
            (bot_name, f"{date_str}%"),
        )
        trade_count = cursor.fetchone()["trade_count"]

        state = get_bot_state(bot_name)
        balance = state["balance"] if state else INITIAL_BALANCE
        is_active = state["is_active"] if state else 1

        return {
            "bot_name": bot_name,
            "balance": balance,
            "trade_count": trade_count,
            "is_active": bool(is_active),
            "pnl": balance - INITIAL_BALANCE,
            "pnl_pct": ((balance - INITIAL_BALANCE) / INITIAL_BALANCE) * 100,
        }
    finally:
        conn.close()


def get_positions(bot_name):
    """指定ボットの現在ポジション（保有銘柄）を取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT symbol, position, balance
            FROM trades
            WHERE bot_name = ? AND id IN (
                SELECT MAX(id) FROM trades WHERE bot_name = ? GROUP BY symbol
            )
            """,
            (bot_name, bot_name),
        )
        rows = cursor.fetchall()
        return {row["symbol"]: {"position": row["position"], "balance": row["balance"]}
                for row in rows}
    finally:
        conn.close()


# ────────────────────────────────────────────
#  デリバティブ情報 (Bot #10用)
# ────────────────────────────────────────────

def save_derivative_data(timestamp, symbol, funding_rate, open_interest):
    """デリバティブ情報を保存する。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO derivatives "
            "(timestamp, symbol, funding_rate, open_interest) "
            "VALUES (?, ?, ?, ?)",
            (timestamp, symbol, funding_rate, open_interest),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"デリバティブデータ保存エラー: {e}")
    finally:
        conn.close()


def get_latest_derivative(symbol):
    """指定銘柄の最新デリバティブ情報を取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM derivatives WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_recent_trades_all(since):
    """指定時刻以降の全Botの取引履歴を取得する。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM trades WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
