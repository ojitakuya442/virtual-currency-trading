"""
Bot #08: レジーム判定 → 戦略切替 (メタbot)
ボラティリティ・トレンド傾きに基づいて市場レジームを判定し、
レジームに応じてポジションサイズを調整する。
- Trend: 順張りフルロング
- Range: 控えめロング
- HighVol: 全クローズ (リスク回避)
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import volatility, regression_slope, ema, adx

logger = logging.getLogger(__name__)


class BotRegime(BaseBot):
    """市場レジーム判定メタ戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # ボラティリティ
        vol = volatility(close, p["volatility_window"])

        # トレンド傾き
        slope = regression_slope(close, p["trend_window"])

        # EMA (方向確認)
        ema_val = ema(close, p["trend_window"])

        # ADX (トレンド強度)
        adx_vals, _, _ = adx(df, 14)

        last = len(df) - 1
        cur_vol = vol.iloc[last]
        cur_slope = slope.iloc[last]
        cur_ema = ema_val.iloc[last]
        cur_adx = adx_vals.iloc[last]
        c = close.iloc[last]

        if pd.isna(cur_vol) or pd.isna(cur_slope) or pd.isna(cur_adx):
            return self._hold_signal("計算期間不足")

        # ── レジーム判定 ──
        # 過去のボラの分位数で高低判定
        vol_history = vol.iloc[max(0, last - 96):last + 1].dropna()
        vol_mean = vol_history.mean() if len(vol_history) > 0 else cur_vol
        vol_std = vol_history.std() if len(vol_history) > 1 else 0

        is_high_vol = cur_vol > vol_mean + vol_std if vol_std > 0 else False
        is_trending = cur_adx > 25 and abs(cur_slope) > 0

        if is_high_vol:
            regime = "HIGH_VOL"
        elif is_trending:
            regime = "TREND"
        else:
            regime = "RANGE"

        # ── レジーム別ポジション ──
        if regime == "HIGH_VOL":
            return {
                "target_position": 0.0,
                "confidence": 0.6,
                "reason": f"レジーム=HIGH_VOL (vol={cur_vol:.4f}) → 全クローズ",
                "stop_loss": None,
            }

        elif regime == "TREND":
            if cur_slope > 0 and c > cur_ema:
                return {
                    "target_position": 0.7,
                    "confidence": 0.6,
                    "reason": f"レジーム=TREND↑ (ADX={cur_adx:.0f}, slope>0) → 順張り",
                    "stop_loss": None,
                }
            elif cur_slope < 0:
                return {
                    "target_position": 0.0,
                    "confidence": 0.5,
                    "reason": f"レジーム=TREND↓ (slope<0) → 回避",
                    "stop_loss": None,
                }
            else:
                return {
                    "target_position": 0.3,
                    "confidence": 0.4,
                    "reason": f"レジーム=TREND (方向不明) → 控えめ",
                    "stop_loss": None,
                }

        else:  # RANGE
            return {
                "target_position": 0.3,
                "confidence": 0.4,
                "reason": f"レジーム=RANGE → 控えめロング",
                "stop_loss": None,
            }
