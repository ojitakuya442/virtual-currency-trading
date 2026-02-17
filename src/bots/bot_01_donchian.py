"""
Bot #01: Donchian ブレイクアウト (トレンド追随)
過去N本の最高値ブレイクで買い・最安値ブレイクで売り。
ATRベースのトレーリングストップを併用。
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import donchian_channel, atr, ema

logger = logging.getLogger(__name__)


class BotDonchian(BaseBot):
    """Donchian Channel ブレイクアウト戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # Donchian Channel
        dc_upper, dc_lower, dc_mid = donchian_channel(df, p["channel_period"])

        # ATR (トレーリングストップ用)
        atr_vals = atr(df, p["atr_period"])

        # トレンド確認用 EMA
        ema_long = ema(close, p["channel_period"])

        # 最新値
        last = len(df) - 1
        c = close.iloc[last]
        prev_c = close.iloc[last - 1]
        upper = dc_upper.iloc[last]
        lower = dc_lower.iloc[last]
        mid = dc_mid.iloc[last]
        cur_atr = atr_vals.iloc[last]
        cur_ema = ema_long.iloc[last]

        # NaN チェック
        if pd.isna(upper) or pd.isna(lower) or pd.isna(cur_atr):
            return self._hold_signal("計算期間不足")

        # ブレイクアウト判定
        if c > upper and prev_c <= dc_upper.iloc[last - 1]:
            # 上方ブレイクアウト → ロング
            stop_loss = c - cur_atr * p["atr_trail_k"]
            return {
                "target_position": 0.8,
                "confidence": 0.7,
                "reason": f"Donchian上方ブレイク ({c:.0f} > {upper:.0f})",
                "stop_loss": stop_loss,
            }

        elif c < lower and prev_c >= dc_lower.iloc[last - 1]:
            # 下方ブレイクアウト → 全クローズ
            return {
                "target_position": 0.0,
                "confidence": 0.7,
                "reason": f"Donchian下方ブレイク ({c:.0f} < {lower:.0f})",
                "stop_loss": None,
            }

        elif c > cur_ema:
            # EMAより上 → 弱めのロング維持
            return {
                "target_position": 0.4,
                "confidence": 0.4,
                "reason": f"EMA上方トレンド継続 ({c:.0f} > EMA{cur_ema:.0f})",
                "stop_loss": mid - cur_atr * p["atr_trail_k"],
            }

        else:
            # EMAより下 → キャッシュ優先
            return {
                "target_position": 0.1,
                "confidence": 0.3,
                "reason": "下方トレンド — 小さいポジション維持",
                "stop_loss": None,
            }
