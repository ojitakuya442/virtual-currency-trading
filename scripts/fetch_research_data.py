"""
リサーチ用の長期データ取得スクリプト（手動ワークフロー research_data.yml から実行）。

取得対象:
  1. 日足OHLCV: Binance (2020-01-01〜, ページング) と Kraken (直近約720日)
  2. Funding rate 履歴: Binance USDM perp (キャリー戦略H2の検証用)

出力: data/research.db (sqlite)
  - daily_prices(source, symbol, date, open, high, low, close, volume)
  - funding_rates(source, symbol, timestamp, rate)

冪等: 既存テーブルは作り直す（リサーチ用スナップショットであり運用DBとは分離）。
"""
import sys
import time
import sqlite3
import pathlib
import logging

import ccxt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fetch_research")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "research.db"

DAILY_SINCE_MS = 1577836800000  # 2020-01-01T00:00:00Z


def fetch_daily_paginated(exchange, symbol, since_ms, limit=1000):
    """日足を since からページングで全取得する。"""
    out = []
    since = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=limit)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 2:
            break
        nxt = batch[-1][0] + 86_400_000
        if nxt <= since:
            break
        since = nxt
        if since > exchange.milliseconds():
            break
        time.sleep(exchange.rateLimit / 1000)
    # 重複除去
    seen, dedup = set(), []
    for row in out:
        if row[0] not in seen:
            seen.add(row[0])
            dedup.append(row)
    return dedup


def fetch_funding_paginated(exchange, symbol, since_ms, limit=1000):
    out = []
    since = since_ms
    while True:
        try:
            batch = exchange.fetch_funding_rate_history(symbol, since=since, limit=limit)
        except Exception as e:
            log.warning(f"funding取得中断 {symbol}: {e}")
            break
        if not batch:
            break
        out.extend(batch)
        nxt = batch[-1]["timestamp"] + 1
        if nxt <= since or len(batch) < 2:
            break
        since = nxt
        if since > exchange.milliseconds():
            break
        time.sleep(exchange.rateLimit / 1000)
    seen, dedup = set(), []
    for row in out:
        if row["timestamp"] not in seen:
            seen.add(row["timestamp"])
            dedup.append(row)
    return dedup


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    conn.execute("DROP TABLE IF EXISTS daily_prices")
    conn.execute("DROP TABLE IF EXISTS funding_rates")
    conn.execute(
        "CREATE TABLE daily_prices (source TEXT, symbol TEXT, date TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "PRIMARY KEY(source, symbol, date))")
    conn.execute(
        "CREATE TABLE funding_rates (source TEXT, symbol TEXT, timestamp TEXT, rate REAL, "
        "PRIMARY KEY(source, symbol, timestamp))")

    from datetime import datetime, timezone
    to_date = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    to_iso = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

    # ── 1. Binance 日足 (2020〜) ──
    try:
        binance = ccxt.binance({"enableRateLimit": True})
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            rows = fetch_daily_paginated(binance, symbol, DAILY_SINCE_MS)
            conn.executemany(
                "INSERT OR REPLACE INTO daily_prices VALUES ('binance', ?, ?, ?, ?, ?, ?, ?)",
                [(symbol, to_date(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows])
            conn.commit()
            log.info(f"binance {symbol}: {len(rows)}日分")
    except Exception as e:
        log.error(f"Binance日足の取得に失敗: {e}")

    # ── 2. Kraken 日足 (約720日・クロスチェック用) ──
    try:
        kraken = ccxt.kraken({"enableRateLimit": True})
        for symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
            rows = kraken.fetch_ohlcv(symbol, timeframe="1d", limit=720)
            conn.executemany(
                "INSERT OR REPLACE INTO daily_prices VALUES ('kraken', ?, ?, ?, ?, ?, ?, ?)",
                [(symbol, to_date(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows])
            conn.commit()
            log.info(f"kraken {symbol}: {len(rows)}日分")
            time.sleep(1)
    except Exception as e:
        log.error(f"Kraken日足の取得に失敗: {e}")

    # ── 3. Binance USDM funding rate 履歴 (キャリー検証用) ──
    try:
        um = ccxt.binanceusdm({"enableRateLimit": True})
        for symbol in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"):
            rows = fetch_funding_paginated(um, symbol, DAILY_SINCE_MS)
            conn.executemany(
                "INSERT OR REPLACE INTO funding_rates VALUES ('binanceusdm', ?, ?, ?)",
                [(symbol, to_iso(r["timestamp"]), float(r["fundingRate"] or 0)) for r in rows])
            conn.commit()
            log.info(f"funding {symbol}: {len(rows)}件")
    except Exception as e:
        log.error(f"Funding履歴の取得に失敗: {e}")

    n_p = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    n_f = conn.execute("SELECT COUNT(*) FROM funding_rates").fetchone()[0]
    conn.close()
    log.info(f"完了: daily_prices={n_p}行, funding_rates={n_f}行 → {DB}")
    if n_p == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
