"""
Bot #05: ボラティリティ Squeeze (収縮→拡大ブレイク)
ボリンジャーバンド幅が過去N本の下位X%に収縮したら待機状態へ。
拡大開始（BW増加）+ 方向確認で順張りエントリー。
"""
import logging
import pandas as pd
import numpy as np

from src.strategy import BaseBot
from src.indicators import bollinger_bands, atr, ema

logger = logging.getLogger(__name__)


class BotSqueeze(BaseBot):
    """ボラ収縮 → 拡大ブレイクアウト戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # Bollinger Bands (bandwidth含む)
        bb_mid, bb_upper, bb_lower, bb_bw, bb_zscore = bollinger_bands(
            close, p["bb_period"], p["bb_std"]
        )

        # ATR (ストップ用)
        atr_vals = atr(df, p["atr_period"])

        last = len(df) - 1
        c = close.iloc[last]

        if last < p["lookback"] or pd.isna(bb_bw.iloc[last]):
            return self._hold_signal("計算期間不足")

        cur_bw = bb_bw.iloc[last]
        prev_bw = bb_bw.iloc[last - 1]
        cur_atr = atr_vals.iloc[last]

        # 過去N本のBW分位
        lookback_bw = bb_bw.iloc[max(0, last - p["lookback"]):last + 1].dropna()
        if len(lookback_bw) < p["lookback"] // 2:
            return self._hold_signal("BW計算期間不足")

        bw_percentile = (lookback_bw < cur_bw).sum() / len(lookback_bw)

        # ── Squeeze 検出 → 拡大開始待ち ──
        is_squeeze = bw_percentile <= p["bandwidth_low_pct"]
        is_expanding = cur_bw > prev_bw  # BWが拡大中

        if is_squeeze and not is_expanding:
            # 収縮中 — まだ待機
            return {
                "target_position": 0.1,
                "confidence": 0.3,
                "reason": f"Squeeze検出 (BW={cur_bw:.4f}, 分位={bw_percentile:.0%}) — 待機中",
                "stop_loss": None,
            }

        if is_squeeze and is_expanding:
            # 収縮→拡大開始！方向を確認
            prev_close = close.iloc[last - 1]

            if c > bb_mid.iloc[last]:
                # 上方向拡大 → ロング
                stop = c - cur_atr * p["atr_trail_k"]
                return {
                    "target_position": 0.7,
                    "confidence": 0.7,
                    "reason": f"Squeeze拡大ブレイク↑ (BW={cur_bw:.4f}→上方)",
                    "stop_loss": stop,
                }
            else:
                # 下方向拡大 → 回避
                return {
                    "target_position": 0.0,
                    "confidence": 0.5,
                    "reason": f"Squeeze拡大ブレイク↓ (下方向 → クローズ)",
                    "stop_loss": None,
                }

        # ── 通常状態 ──
        if c > bb_mid.iloc[last]:
            return {
                "target_position": 0.3,
                "confidence": 0.3,
                "reason": "BB中央上方 — 弱ロング",
                "stop_loss": None,
            }

        return {
            "target_position": 0.0,
            "confidence": 0.2,
            "reason": "シグナルなし",
            "stop_loss": None,
        }
