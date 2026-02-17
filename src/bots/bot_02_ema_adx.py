"""
Bot #02: EMA トレンド + ADX フィルタ (ダマシ回避)
EMA短期/長期のクロスに加え、ADXが一定以上のときだけエントリー。
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.indicators import ema, adx

logger = logging.getLogger(__name__)


class BotEmaAdx(BaseBot):
    """EMAクロス + ADXフィルタ戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params
        close = df["close"].astype(float)

        # EMA
        ema_s = ema(close, p["ema_short"])
        ema_l = ema(close, p["ema_long"])

        # ADX
        adx_vals, plus_di, minus_di = adx(df, p["adx_period"])

        last = len(df) - 1
        cur_ema_s = ema_s.iloc[last]
        cur_ema_l = ema_l.iloc[last]
        cur_adx = adx_vals.iloc[last]
        cur_plus_di = plus_di.iloc[last]
        cur_minus_di = minus_di.iloc[last]

        if pd.isna(cur_adx) or pd.isna(cur_ema_s):
            return self._hold_signal("計算期間不足")

        trend_up = cur_ema_s > cur_ema_l
        strong_trend = cur_adx >= p["adx_threshold"]

        if trend_up and strong_trend and cur_plus_di > cur_minus_di:
            # 上昇トレンド + ADX強 + DI+優勢 → フルロング
            return {
                "target_position": 0.8,
                "confidence": 0.7,
                "reason": f"EMAゴールデンクロス + ADX={cur_adx:.0f} (強トレンド)",
                "stop_loss": None,
            }

        elif trend_up and not strong_trend:
            # 上昇トレンドだがADX弱い → 控えめロング
            return {
                "target_position": 0.3,
                "confidence": 0.4,
                "reason": f"EMA上向きだがADX={cur_adx:.0f} (弱トレンド)",
                "stop_loss": None,
            }

        elif not trend_up and strong_trend and cur_minus_di > cur_plus_di:
            # 下降トレンド + ADX強 + DI-優勢 → 全クローズ
            return {
                "target_position": 0.0,
                "confidence": 0.6,
                "reason": f"EMAデッドクロス + ADX={cur_adx:.0f} (下降トレンド)",
                "stop_loss": None,
            }

        else:
            # トレンド不明 → 現金比率高め
            return {
                "target_position": 0.1,
                "confidence": 0.3,
                "reason": "方向性不明 — 様子見",
                "stop_loss": None,
            }
