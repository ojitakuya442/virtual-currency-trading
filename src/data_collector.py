"""
仮想通貨自動売買Bot - データ収集モジュール
Kraken公開APIからの価格データ取得 + Futures API（funding/OI）対応。
"""
import time
import logging
import ccxt
import pandas as pd
from datetime import datetime, timezone

from src.config import (
    EXCHANGE_ID, SYMBOLS, INTERVAL, INTERVAL_MINUTES,
    MAX_RETRIES, RETRY_BASE_DELAY, ANOMALY_THRESHOLD,
)

logger = logging.getLogger(__name__)


def create_exchange():
    """CCXT取引所インスタンスを生成する（現物用）。"""
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    exchange = exchange_class({
        "enableRateLimit": True,
    })
    return exchange


def create_futures_exchange():
    """CCXT先物取引所インスタンスを生成する（funding/OI取得用）。"""
    try:
        exchange = ccxt.krakenfutures({
            "enableRateLimit": True,
        })
        return exchange
    except Exception:
        # fallback: 同一取引所で future オプション
        exchange_class = getattr(ccxt, EXCHANGE_ID)
        exchange = exchange_class({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        return exchange


def fetch_current_prices(exchange=None):
    """
    全対象銘柄の現在価格を取得する。

    Returns:
        dict: {symbol: {"price": float, "timestamp": str, "volume": float}}
    """
    if exchange is None:
        exchange = create_exchange()

    results = {}
    for symbol in SYMBOLS:
        price_data = _fetch_ticker_with_retry(exchange, symbol)
        if price_data:
            results[symbol] = price_data
    return results


def fetch_usd_jpy_rate(exchange=None):
    """
    Krakenから現在のUSD/JPYレートを取得する。
    取得できない場合は config.USD_JPY_RATE (固定値) を返す。
    """
    from src.config import USD_JPY_TICKER, USD_JPY_RATE

    if exchange is None:
        exchange = create_exchange()

    try:
        ticker = exchange.fetch_ticker(USD_JPY_TICKER)
        price = ticker["last"]
        if price and price > 0:
            return price
    except Exception as e:
        logger.warning(f"USD/JPYレート取得エラー: {e}")
    
    return USD_JPY_RATE  # フォールバック


def fetch_ohlcv(exchange, symbol, timeframe="5m", since=None, limit=500):
    """
    指定銘柄のOHLCVデータを取得する。

    Returns:
        pd.DataFrame: OHLCV データフレーム
    """
    for attempt in range(MAX_RETRIES):
        try:
            ohlcv = exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=since, limit=limit
            )
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["symbol"] = symbol
            return df

        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"[{symbol}] OHLCV取得失敗 (試行{attempt + 1}/{MAX_RETRIES}): {e}. "
                f"{delay}秒後にリトライ..."
            )
            time.sleep(delay)
        except ccxt.ExchangeError as e:
            logger.error(f"[{symbol}] 取引所エラー: {e}")
            return None

    logger.error(f"[{symbol}] OHLCV取得に{MAX_RETRIES}回失敗しました。")
    return None


def fetch_historical_data(exchange, symbol, days=30, timeframe="5m"):
    """
    指定銘柄の過去データを一括取得する。

    Returns:
        pd.DataFrame: 全期間のOHLCVデータ
    """
    all_data = []
    since = exchange.parse8601(
        (datetime.now(timezone.utc) - pd.Timedelta(days=days)).isoformat()
    )

    logger.info(f"[{symbol}] 過去{days}日分のデータを取得中...")

    while True:
        df = fetch_ohlcv(exchange, symbol, timeframe=timeframe, since=since, limit=1000)
        if df is None or df.empty:
            break

        all_data.append(df)
        last_ts = int(df["timestamp"].iloc[-1].timestamp() * 1000)
        since = last_ts + 1

        if last_ts >= int(datetime.now(timezone.utc).timestamp() * 1000):
            break

        time.sleep(exchange.rateLimit / 1000)

    if all_data:
        result = pd.concat(all_data, ignore_index=True)
        result = result.drop_duplicates(subset=["timestamp", "symbol"])
        result = result.sort_values("timestamp").reset_index(drop=True)
        logger.info(f"[{symbol}] {len(result)}件のデータを取得完了")
        return result

    logger.warning(f"[{symbol}] データを取得できませんでした。")
    return pd.DataFrame()


# ────────────────────────────────────────────
#  デリバティブ情報取得 (Bot #10用)
# ────────────────────────────────────────────

def fetch_funding_rate(exchange_futures=None, symbol="BTC/USDT"):
    """
    Funding rate を取得する (Kraken Futures)。

    Returns:
        dict: {"funding_rate": float, "timestamp": str} or None
    """
    if exchange_futures is None:
        exchange_futures = create_futures_exchange()

    try:
        # CCXT v4: fetch_funding_rate
        funding = exchange_futures.fetch_funding_rate(symbol)
        return {
            "funding_rate": funding.get("fundingRate", 0),
            "timestamp": funding.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "next_funding_time": funding.get("fundingTimestamp"),
        }
    except Exception as e:
        logger.warning(f"[{symbol}] Funding rate取得エラー: {e}")
        return None


def fetch_open_interest(exchange_futures=None, symbol="BTC/USDT"):
    """
    Open Interest (未決済建玉) を取得する。

    Returns:
        dict: {"open_interest": float, "timestamp": str} or None
    """
    if exchange_futures is None:
        exchange_futures = create_futures_exchange()

    try:
        # Kraken Futures の OI 取得
        oi = exchange_futures.fetch_open_interest(symbol)
        return {
            "open_interest": oi.get("openInterestAmount", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"[{symbol}] Open Interest取得エラー: {e}")
        return None


# ────────────────────────────────────────────
#  内部ヘルパー
# ────────────────────────────────────────────

def _fetch_ticker_with_retry(exchange, symbol):
    """指数バックオフ方式でticker取得をリトライする。"""
    for attempt in range(MAX_RETRIES):
        try:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker["last"]

            if price is None or price <= 0:
                logger.warning(f"[{symbol}] 無効な価格: {price}")
                return None

            return {
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "volume": ticker.get("quoteVolume", 0),
                "bid": ticker.get("bid", 0),
                "ask": ticker.get("ask", 0),
                "high": ticker.get("high", 0),
                "low": ticker.get("low", 0),
            }

        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"[{symbol}] 価格取得失敗 (試行{attempt + 1}/{MAX_RETRIES}): {e}. "
                f"{delay}秒後にリトライ..."
            )
            time.sleep(delay)
        except ccxt.ExchangeError as e:
            logger.error(f"[{symbol}] 取引所エラー: {e}")
            return None

    logger.error(f"[{symbol}] 価格取得に{MAX_RETRIES}回失敗しました。")
    return None


def validate_price_change(current_price, previous_price):
    """価格の変動率をチェックし、異常値かどうかを判定する。"""
    if previous_price is None or previous_price == 0:
        return True

    change_rate = abs(current_price - previous_price) / previous_price
    if change_rate > ANOMALY_THRESHOLD:
        logger.warning(
            f"異常な価格変動を検出: {previous_price} → {current_price} "
            f"(変動率: {change_rate:.2%})"
        )
        return False

    return True
