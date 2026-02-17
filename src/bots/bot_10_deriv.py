"""
Bot #10: デリバティブ情報併用 (Funding Rate / Open Interest)
Binance Futures の funding rate と OI を環境情報として利用。
- Funding高→ロング過熱 → 利確/クローズ
- Funding低+OI急増 → 新規ロングチャンス
- OI急減 → ポジション解消圧力
"""
import logging
import pandas as pd

from src.strategy import BaseBot
from src.data_collector import fetch_funding_rate, fetch_open_interest
from src.database import get_latest_derivative, save_derivative_data

logger = logging.getLogger(__name__)


class BotDerivatives(BaseBot):
    """デリバティブ情報併用戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        p = self.params

        # Funding rate / OI を取得
        funding_data = fetch_funding_rate(symbol=symbol)
        oi_data = fetch_open_interest(symbol=symbol)

        if funding_data is None or oi_data is None:
            return self._hold_signal("デリバティブデータ取得失敗")

        funding_rate = funding_data["funding_rate"]
        current_oi = oi_data["open_interest"]

        # デリバデータをDB保存
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        save_derivative_data(now, symbol, funding_rate, current_oi)

        # 前回のOI取得 (変動率計算用)
        prev_deriv = get_latest_derivative(symbol)
        if prev_deriv and prev_deriv["open_interest"] and prev_deriv["open_interest"] > 0:
            oi_change = (current_oi - prev_deriv["open_interest"]) / prev_deriv["open_interest"]
        else:
            oi_change = 0.0

        # ── 判定ロジック ──

        # Funding rate 過熱判定
        if funding_rate > p["funding_extreme_pct"]:
            # ロング過熱 → 利確方向 (反転リスク高)
            return {
                "target_position": 0.0,
                "confidence": 0.6,
                "reason": f"FR={funding_rate:.4f} 過熱 (ロング偏り) → クローズ",
                "stop_loss": None,
            }

        if funding_rate < -p["funding_extreme_pct"]:
            # ショート過熱 → ロングチャンス
            pos = 0.6
            if oi_change > p["oi_change_threshold"]:
                pos = 0.8  # OI急増 = 新規参入 → 強め
            return {
                "target_position": pos,
                "confidence": 0.6,
                "reason": f"FR={funding_rate:.4f} (ショート過熱) + OI変動={oi_change:.1%} → ロング",
                "stop_loss": None,
            }

        # OI急減 → 精算圧力 → 回避
        if oi_change < -p["oi_change_threshold"]:
            return {
                "target_position": 0.0,
                "confidence": 0.5,
                "reason": f"OI急減 ({oi_change:.1%}) → ポジション解消圧力",
                "stop_loss": None,
            }

        # OI急増 + 中立Funding → 新規参入増、やや強気
        if oi_change > p["oi_change_threshold"]:
            return {
                "target_position": 0.5,
                "confidence": 0.5,
                "reason": f"OI急増 ({oi_change:.1%}) + FR中立 → やや強気",
                "stop_loss": None,
            }

        # 通常状態
        return {
            "target_position": 0.2,
            "confidence": 0.3,
            "reason": f"デリバ中立 (FR={funding_rate:.4f}, OI変動={oi_change:.1%})",
            "stop_loss": None,
        }
