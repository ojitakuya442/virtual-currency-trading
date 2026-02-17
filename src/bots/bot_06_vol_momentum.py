"""
Bot #06: 出来高 × リターン モメンタム
出来高で重み付けしたモメンタムスコアと、OBVの方向を組み合わせて
「本物のモメンタム」と「だまし」を判別する。
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import volume_weighted_momentum, obv, sma

logger = logging.getLogger(__name__)


class BotVolMomentum(BaseBot):
    """出来高 × リターン モメンタム戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # 出来高加重モメンタム
        vw_mom = volume_weighted_momentum(df, p["momentum_period"])

        # OBV + SMA
        obv_vals = obv(df)
        obv_trend = sma(obv_vals, p["obv_sma_period"])

        # 出来高 z-score
        vol = df["volume"].astype(float)
        vol_mean = sma(vol, p["volume_zscore_period"])
        vol_std = vol.rolling(window=p["volume_zscore_period"], min_periods=p["volume_zscore_period"]).std()
        vol_zscore = (vol - vol_mean) / vol_std.replace(0, float("nan"))

        last = len(df) - 1
        cur_mom = vw_mom.iloc[last]
        cur_obv = obv_vals.iloc[last]
        cur_obv_sma = obv_trend.iloc[last]
        cur_vol_z = vol_zscore.iloc[last]

        if pd.isna(cur_mom) or pd.isna(cur_obv_sma) or pd.isna(cur_vol_z):
            return self._hold_signal("計算期間不足")

        obv_bullish = cur_obv > cur_obv_sma  # OBV が上昇トレンド

        # ── 強気モメンタム ──
        if cur_mom > 0 and obv_bullish:
            if cur_vol_z > 1.0:
                # 高モメンタム + OBV上昇 + 出来高急増 → 強シグナル
                return {
                    "target_position": 0.8,
                    "confidence": 0.7,
                    "reason": f"出来高モメンタム強気 (VWM={cur_mom:.0f}, OBV↑, 出来高z={cur_vol_z:.1f})",
                    "stop_loss": None,
                }
            else:
                return {
                    "target_position": 0.5,
                    "confidence": 0.5,
                    "reason": f"モメンタム強気 (VWM={cur_mom:.0f}, OBV↑)",
                    "stop_loss": None,
                }

        # ── 弱気モメンタム ──
        elif cur_mom < 0 and not obv_bullish:
            return {
                "target_position": 0.0,
                "confidence": 0.5,
                "reason": f"モメンタム弱気 (VWM={cur_mom:.0f}, OBV↓)",
                "stop_loss": None,
            }

        # ── ダイバージェンス: モメンタムとOBV不一致 ──
        elif cur_mom > 0 and not obv_bullish:
            return {
                "target_position": 0.2,
                "confidence": 0.3,
                "reason": f"ダイバージェンス: 価格↑ but OBV↓ (要警戒)",
                "stop_loss": None,
            }

        else:
            return {
                "target_position": 0.1,
                "confidence": 0.3,
                "reason": "方向性不明",
                "stop_loss": None,
            }
