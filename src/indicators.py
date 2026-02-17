"""
仮想通貨自動売買Bot - テクニカル指標モジュール
10bot 対応版: SMA, EMA, RSI, MACD, BB, ATR, Donchian, ADX, VWAP, OBV 等
"""
import numpy as np
import pandas as pd


# ────────────────────────────────────────────
#  基本指標
# ────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    """単純移動平均"""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移動平均"""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ────────────────────────────────────────────
#  MACD
# ────────────────────────────────────────────

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD を計算する。

    Returns:
        (macd_line, signal_line, histogram)
    """
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ────────────────────────────────────────────
#  ボリンジャーバンド
# ────────────────────────────────────────────

def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    """
    ボリンジャーバンドを計算する。

    Returns:
        (middle, upper, lower, bandwidth, zscore)
    """
    middle = sma(series, period)
    rolling_std = series.rolling(window=period, min_periods=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    bandwidth = (upper - lower) / middle  # バンド幅 (Squeeze検出用)
    zscore = (series - middle) / rolling_std.replace(0, np.nan)
    return middle, upper, lower, bandwidth, zscore


# ────────────────────────────────────────────
#  ATR (Average True Range)
# ────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR を計算する (high, low, close が必要)。"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1 / period, min_periods=period).mean()


# ────────────────────────────────────────────
#  Donchian Channel
# ────────────────────────────────────────────

def donchian_channel(df: pd.DataFrame, period: int = 48):
    """
    Donchian Channel を計算する。

    Returns:
        (upper, lower, mid)
    """
    upper = df["high"].rolling(window=period, min_periods=period).max()
    lower = df["low"].rolling(window=period, min_periods=period).min()
    mid = (upper + lower) / 2
    return upper, lower, mid


# ────────────────────────────────────────────
#  ADX / DI+ / DI-
# ────────────────────────────────────────────

def adx(df: pd.DataFrame, period: int = 14):
    """
    ADX, +DI, -DI を計算する。

    Returns:
        (adx_series, plus_di, minus_di)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)

    # +DM > -DM の場合のみ +DM を有効化 (逆も同様)
    mask_plus = plus_dm > minus_dm
    mask_minus = minus_dm > plus_dm
    plus_dm = plus_dm.where(mask_plus, 0)
    minus_dm = minus_dm.where(mask_minus, 0)

    # 平滑化
    atr_smooth = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / period, min_periods=period).mean()

    plus_di = 100 * plus_dm_smooth / atr_smooth.replace(0, np.nan)
    minus_di = 100 * minus_dm_smooth / atr_smooth.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return adx_series, plus_di, minus_di


# ────────────────────────────────────────────
#  VWAP (Volume Weighted Average Price)
# ────────────────────────────────────────────

def vwap(df: pd.DataFrame, period: int = 48) -> pd.Series:
    """ローリングVWAPを計算する。"""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]

    cum_tp_vol = tp_vol.rolling(window=period, min_periods=1).sum()
    cum_vol = df["volume"].rolling(window=period, min_periods=1).sum()

    return cum_tp_vol / cum_vol.replace(0, np.nan)


# ────────────────────────────────────────────
#  OBV (On-Balance Volume)
# ────────────────────────────────────────────

def obv(df: pd.DataFrame) -> pd.Series:
    """OBV (On-Balance Volume) を計算する。"""
    direction = np.sign(df["close"].diff())
    direction.iloc[0] = 0
    return (direction * df["volume"]).cumsum()


# ────────────────────────────────────────────
#  出来高加重モメンタム
# ────────────────────────────────────────────

def volume_weighted_momentum(df: pd.DataFrame, period: int = 12) -> pd.Series:
    """過去n本の (リターン × 出来高) の合計。"""
    returns = df["close"].pct_change()
    vol_return = returns * df["volume"]
    return vol_return.rolling(window=period, min_periods=period).sum()


# ────────────────────────────────────────────
#  ボラティリティ
# ────────────────────────────────────────────

def volatility(series: pd.Series, period: int = 24) -> pd.Series:
    """リターンの標準偏差 (実現ボラティリティ)。"""
    returns = series.pct_change()
    return returns.rolling(window=period, min_periods=period).std()


def price_change_pct(series: pd.Series, period: int = 1) -> pd.Series:
    """N本前からの変化率。"""
    return series.pct_change(periods=period)


# ────────────────────────────────────────────
#  回帰傾き (Linear Regression Slope)
# ────────────────────────────────────────────

def regression_slope(series: pd.Series, period: int = 24) -> pd.Series:
    """過去N本の線形回帰の傾きを計算する。"""
    def _slope(window):
        if len(window) < period:
            return np.nan
        x = np.arange(len(window))
        try:
            coeffs = np.polyfit(x, window, 1)
            return coeffs[0]
        except (np.linalg.LinAlgError, ValueError):
            return np.nan

    return series.rolling(window=period, min_periods=period).apply(_slope, raw=True)


# ────────────────────────────────────────────
#  一括指標計算 (各bot向けヘルパー)
# ────────────────────────────────────────────

def add_core_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    共通的に使われるコア指標を一括追加する。
    各botは必要に応じて追加でbot固有の指標を計算する。

    追加カラム:
        ema_12, ema_48, rsi_14, macd_line, macd_signal, macd_hist,
        bb_mid, bb_upper, bb_lower, bb_bandwidth, bb_zscore,
        atr_14, volatility_24, price_change_1
    """
    close = df["close"].astype(float)

    # EMA
    df["ema_12"] = ema(close, 12)
    df["ema_48"] = ema(close, 48)

    # RSI
    df["rsi_14"] = rsi(close, 14)

    # MACD
    df["macd_line"], df["macd_signal"], df["macd_hist"] = macd(close)

    # Bollinger Bands
    df["bb_mid"], df["bb_upper"], df["bb_lower"], df["bb_bandwidth"], df["bb_zscore"] = \
        bollinger_bands(close, 20, 2.0)

    # ATR
    df["atr_14"] = atr(df, 14)

    # Volatility
    df["volatility_24"] = volatility(close, 24)

    # Price change
    df["price_change_1"] = price_change_pct(close, 1)

    return df
