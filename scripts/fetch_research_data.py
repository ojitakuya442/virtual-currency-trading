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

    # ── 1. Yahoo Finance 日足 (最長10年。Binance は Actions ランナーを
    #      HTTP 451 でジオブロックするため代替。2026-07-06 変更) ──
    import requests
    for yf_ticker, symbol in (("BTC-USD", "BTC/USD"), ("ETH-USD", "ETH/USD"), ("SOL-USD", "SOL/USD")):
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}",
                params={"range": "10y", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            rows = [
                (symbol, to_date(t * 1000), o, h, l, c, v)
                for t, o, h, l, c, v in zip(ts, q["open"], q["high"], q["low"], q["close"], q["volume"])
                if c is not None
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO daily_prices VALUES ('yahoo', ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.commit()
            log.info(f"yahoo {symbol}: {len(rows)}日分 ({rows[0][1]}〜{rows[-1][1]})")
            time.sleep(1)
        except Exception as e:
            log.error(f"Yahoo日足の取得に失敗 ({yf_ticker}): {e}")

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

    # ── 3. Kraken Futures funding rate 履歴 (キャリー検証用。
    #      Binance はジオブロックのため Kraken に変更。2026-07-06) ──
    try:
        kf = ccxt.krakenfutures({"enableRateLimit": True})
        for symbol in ("BTC/USD:USD", "ETH/USD:USD", "SOL/USD:USD"):
            rows = fetch_funding_paginated(kf, symbol, DAILY_SINCE_MS)
            conn.executemany(
                "INSERT OR REPLACE INTO funding_rates VALUES ('krakenfutures', ?, ?, ?)",
                [(symbol, to_iso(r["timestamp"]), float(r["fundingRate"] or 0)) for r in rows])
            conn.commit()
            log.info(f"funding {symbol}: {len(rows)}件")
            time.sleep(1)
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
