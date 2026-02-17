"""
Bot #04: VWAP アンカー (回帰/順張り切替)
価格とVWAPの乖離率に基づく戦略。
・乖離大 + 出来高急増 → 順張り (ブレイクアウト)
・乖離大 + 出来高通常 → 逆張り (回帰)
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import vwap, sma

logger = logging.getLogger(__name__)


class BotVWAP(BaseBot):
    """VWAP アンカー戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # ローリングVWAP
        cur_vwap = vwap(df, p["vwap_period"])

        # 出来高平均
        vol_sma = sma(df["volume"].astype(float), p["vwap_period"])

        last = len(df) - 1
        c = close.iloc[last]
        v = cur_vwap.iloc[last]
        vol = df["volume"].iloc[last]
        vol_avg = vol_sma.iloc[last]

        if pd.isna(v) or pd.isna(vol_avg) or vol_avg == 0:
            return self._hold_signal("計算期間不足")

        deviation = (c - v) / v  # VWAP乖離率
        vol_ratio = vol / vol_avg  # 出来高比率
        is_volume_surge = vol_ratio >= p["volume_surge_k"]

        # ── 上方乖離 ──
        if deviation > p["deviation_threshold"]:
            if is_volume_surge:
                # VWAP上方 + 出来高急増 → 順張りロング
                return {
                    "target_position": 0.7,
                    "confidence": 0.6,
                    "reason": f"VWAP上方ブレイク (乖離={deviation:.2%}, 出来高{vol_ratio:.1f}倍)",
                    "stop_loss": v,
                }
            else:
                # VWAP上方 + 出来高普通 → 利確方向
                return {
                    "target_position": 0.1,
                    "confidence": 0.4,
                    "reason": f"VWAP上方乖離 (出来高不足) → 利確モード",
                    "stop_loss": None,
                }

        # ── 下方乖離 ──
        elif deviation < -p["deviation_threshold"]:
            if is_volume_surge:
                # VWAP下方 + 出来高急増 → 下落トレンド、回避
                return {
                    "target_position": 0.0,
                    "confidence": 0.5,
                    "reason": f"VWAP下方+出来高急増 (パニック売り→回避)",
                    "stop_loss": None,
                }
            else:
                # VWAP下方 + 出来高普通 → 回帰期待ロング
                return {
                    "target_position": 0.5,
                    "confidence": 0.5,
                    "reason": f"VWAP下方乖離 (回帰期待ロング, 乖離={deviation:.2%})",
                    "stop_loss": c * 0.97,
                }

        # ── VWAP近辺 ──
        else:
            return {
                "target_position": 0.2,
                "confidence": 0.3,
                "reason": f"VWAP近辺 (乖離={deviation:.2%}) — 待機",
                "stop_loss": None,
            }
