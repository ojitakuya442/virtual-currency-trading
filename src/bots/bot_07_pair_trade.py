"""
Bot #07: ペアトレード BTC-ETH
BTC/ETH 相対価格の z-score ベースのマーケットニュートラル戦略。
ロングのみ制約があるため、「相対的に割安な方を買う」形で運用。
"""
import logging
import pandas as pd
import numpy as np

from src.strategy import BaseBot
from src.indicators import sma

logger = logging.getLogger(__name__)


class BotPairTrade(BaseBot):
    """BTC-ETH ペアトレード戦略"""

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        """
        このbotは get_signals をオーバーライドして2銘柄同時判断する。
        compute_signal 単体ではダミーを返す。
        """
        return self._hold_signal("ペアトレードは get_signals を使用")

    def get_signals(self, data_dict: dict) -> dict:
        """
        BTC/ETH の相対価格スプレッドに基づくシグナル。
        """
        p = self.params
        btc_key = "BTC/USDT"
        eth_key = "ETH/USDT"

        if btc_key not in data_dict or eth_key not in data_dict:
            return {
                btc_key: self._hold_signal("ペアデータ不足"),
                eth_key: self._hold_signal("ペアデータ不足"),
            }

        df_btc = data_dict[btc_key]
        df_eth = data_dict[eth_key]

        if df_btc is None or df_eth is None or len(df_btc) < 50 or len(df_eth) < 50:
            return {
                btc_key: self._hold_signal("データ不足"),
                eth_key: self._hold_signal("データ不足"),
            }

        try:
            # 長さを揃える
            min_len = min(len(df_btc), len(df_eth))
            btc_close = df_btc["close"].astype(float).iloc[-min_len:].reset_index(drop=True)
            eth_close = df_eth["close"].astype(float).iloc[-min_len:].reset_index(drop=True)

            # スプレッド = log(BTC) - log(ETH) の正規化
            spread = np.log(btc_close) - np.log(eth_close)
            spread_mean = sma(spread, p["spread_period"])
            spread_std = spread.rolling(window=p["spread_period"], min_periods=p["spread_period"]).std()

            last = len(spread) - 1
            cur_mean = spread_mean.iloc[last]
            cur_std = spread_std.iloc[last]

            if pd.isna(cur_mean) or pd.isna(cur_std) or cur_std == 0:
                return {
                    btc_key: self._hold_signal("スプレッド計算不足"),
                    eth_key: self._hold_signal("スプレッド計算不足"),
                }

            zscore = (spread.iloc[last] - cur_mean) / cur_std

            # ── z-score 判定 ──
            if zscore > p["zscore_entry"]:
                # BTC相対的に割高 → ETHを買い (BTCは売り→0)
                return {
                    btc_key: {
                        "target_position": 0.0,
                        "confidence": 0.6,
                        "reason": f"ペアトレ: BTC割高 (z={zscore:.2f}) → BTC売り",
                        "stop_loss": None,
                    },
                    eth_key: {
                        "target_position": 0.7,
                        "confidence": 0.6,
                        "reason": f"ペアトレ: ETH割安 (z={zscore:.2f}) → ETH買い",
                        "stop_loss": None,
                    },
                }

            elif zscore < -p["zscore_entry"]:
                # ETH相対的に割高 → BTCを買い (ETHは売り→0)
                return {
                    btc_key: {
                        "target_position": 0.7,
                        "confidence": 0.6,
                        "reason": f"ペアトレ: BTC割安 (z={zscore:.2f}) → BTC買い",
                        "stop_loss": None,
                    },
                    eth_key: {
                        "target_position": 0.0,
                        "confidence": 0.6,
                        "reason": f"ペアトレ: ETH割高 (z={zscore:.2f}) → ETH売り",
                        "stop_loss": None,
                    },
                }

            elif abs(zscore) < p["zscore_exit"]:
                # 中立 → 両方ノーポジ
                return {
                    btc_key: {
                        "target_position": 0.0,
                        "confidence": 0.3,
                        "reason": f"ペアトレ: z={zscore:.2f} 中立",
                        "stop_loss": None,
                    },
                    eth_key: {
                        "target_position": 0.0,
                        "confidence": 0.3,
                        "reason": f"ペアトレ: z={zscore:.2f} 中立",
                        "stop_loss": None,
                    },
                }

            else:
                # 損切りゾーン (|z| > stop)
                if abs(zscore) > p["zscore_stop"]:
                    return {
                        btc_key: {
                            "target_position": 0.0,
                            "confidence": 0.5,
                            "reason": f"ペアトレ: z={zscore:.2f} ストップ",
                            "stop_loss": None,
                        },
                        eth_key: {
                            "target_position": 0.0,
                            "confidence": 0.5,
                            "reason": f"ペアトレ: z={zscore:.2f} ストップ",
                            "stop_loss": None,
                        },
                    }

                # exit ~ entry の間 → 維持
                return {
                    btc_key: self._hold_signal(f"ペアトレ: z={zscore:.2f} 維持"),
                    eth_key: self._hold_signal(f"ペアトレ: z={zscore:.2f} 維持"),
                }

        except Exception as e:
            logger.error(f"[{self.name}] ペアトレード計算エラー: {e}")
            return {
                btc_key: self._hold_signal(f"エラー: {e}"),
                eth_key: self._hold_signal(f"エラー: {e}"),
            }
