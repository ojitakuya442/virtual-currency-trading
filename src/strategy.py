"""
仮想通貨自動売買Bot - 戦略基底クラス (BaseBot)
全10botが継承する統一インターフェース。

各botは compute_signal(df, symbol) を実装し、
target_position (0.0 ~ 1.0) を返す。
"""
import logging
import pandas as pd
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseBot(ABC):
    """
    全botが継承する基底クラス。

    統一インターフェース:
        compute_signal(df, symbol) → {
            "target_position": float,  # 0.0（ノーポジ）〜 1.0（フルロング）
            "confidence": float,       # 0.0 ~ 1.0
            "reason": str,
            "stop_loss": float | None,
        }
    """

    def __init__(self, bot_config: dict):
        """
        Args:
            bot_config: BOT_CONFIGS[bot_name] の辞書。
                {
                    "name": "01_donchian",
                    "description": "...",
                    "symbols": [...],
                    "params": {...},
                }
        """
        self.name = bot_config["name"]
        self.description = bot_config["description"]
        self.symbols = bot_config["symbols"]
        self.params = bot_config["params"]

    @abstractmethod
    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        """
        テクニカル指標付きDataFrameから売買シグナルを計算する。

        Args:
            df: OHLCV + 指標カラム付き DataFrame
            symbol: 対象銘柄ペア

        Returns:
            {
                "target_position": float,  # 0.0 ~ 1.0 (ロングのみ)
                "confidence": float,       # シグナルの確信度
                "reason": str,             # 判断理由（ログ/レポート用）
                "stop_loss": float | None, # ストップロス価格 (任意)
            }
        """
        pass

    def get_signals(self, data_dict: dict) -> dict:
        """
        全対象銘柄のシグナルを取得する。

        Args:
            data_dict: {symbol: pd.DataFrame} 各銘柄のOHLCVデータ

        Returns:
            {symbol: signal_dict}
        """
        signals = {}
        for symbol in self.symbols:
            if symbol not in data_dict:
                signals[symbol] = self._hold_signal("データなし")
                continue

            df = data_dict[symbol]
            if df is None or len(df) < 50:  # 最低50本必要
                signals[symbol] = self._hold_signal("データ不足")
                continue

            try:
                signal = self.compute_signal(df, symbol)
                # target_position を 0.0 ~ 1.0 にクランプ
                tp = signal.get("target_position", 0.0)
                signal["target_position"] = max(0.0, min(1.0, tp))
                signals[symbol] = signal
            except Exception as e:
                logger.error(f"[{self.name}][{symbol}] シグナル計算エラー: {e}")
                signals[symbol] = self._hold_signal(f"エラー: {e}")

        return signals

    @staticmethod
    def _hold_signal(reason: str) -> dict:
        """HOLD（target_position=0）のデフォルトシグナル。"""
        return {
            "target_position": 0.0,
            "confidence": 0.0,
            "reason": reason,
            "stop_loss": None,
        }
