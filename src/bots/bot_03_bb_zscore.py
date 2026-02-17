"""
Bot #03: ボリンジャー z-score 平均回帰 (レンジ取り)
z-scoreが±2以上の行き過ぎ局面で逆張り。RSI確認とADXトレンド除外。
トレンド中（ADX高）は停止してダマシを回避。
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import bollinger_bands, rsi, adx

logger = logging.getLogger(__name__)


class BotBBZscore(BaseBot):
    """ボリンジャーバンド z-score 平均回帰戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # Bollinger Bands (z-score含む)
        bb_mid, bb_upper, bb_lower, bb_bw, bb_zscore = bollinger_bands(
            close, p["bb_period"], p["bb_std"]
        )

        # RSI (逆張り確認)
        rsi_vals = rsi(close, p["rsi_period"])

        # ADX (トレンド判定)
        adx_vals, _, _ = adx(df, p["adx_period"])

        last = len(df) - 1
        cur_z = bb_zscore.iloc[last]
        cur_rsi = rsi_vals.iloc[last]
        cur_adx = adx_vals.iloc[last]

        if pd.isna(cur_z) or pd.isna(cur_rsi) or pd.isna(cur_adx):
            return self._hold_signal("計算期間不足")

        # トレンド中はスキップ
        if cur_adx >= p["adx_pause_threshold"]:
            return {
                "target_position": 0.0,
                "confidence": 0.2,
                "reason": f"ADX={cur_adx:.0f} (トレンド中 → 平均回帰停止)",
                "stop_loss": None,
            }

        # 下方に行き過ぎ → 逆張りロング
        if cur_z <= -p["zscore_entry"] and cur_rsi <= p["rsi_confirm"]:
            strength = min(1.0, abs(cur_z) / (p["zscore_entry"] * 1.5))
            return {
                "target_position": 0.5 + 0.3 * strength,
                "confidence": 0.6,
                "reason": f"下方行き過ぎ z={cur_z:.2f}, RSI={cur_rsi:.0f} → 逆張りロング",
                "stop_loss": bb_lower.iloc[last] * 0.98,
            }

        # 上方に行き過ぎ → 利確/クローズ
        if cur_z >= p["zscore_entry"]:
            return {
                "target_position": 0.0,
                "confidence": 0.5,
                "reason": f"上方行き過ぎ z={cur_z:.2f} → 利確クローズ",
                "stop_loss": None,
            }

        # z-scoreが中立近辺 → 平均回帰方向で薄いポジション
        if cur_z < 0 and cur_rsi < 50:
            return {
                "target_position": 0.2,
                "confidence": 0.3,
                "reason": f"z={cur_z:.2f} やや下方 — 控えめロング",
                "stop_loss": None,
            }

        return {
            "target_position": 0.0,
            "confidence": 0.2,
            "reason": "シグナルなし (z-score中立)",
            "stop_loss": None,
        }
