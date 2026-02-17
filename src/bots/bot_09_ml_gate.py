"""
Bot #09: ML ゲート (LightGBM フィルタ)
テクニカル指標を特徴量としてLightGBMで将来リターンを予測。
予測が正のときロング、負のときクローズ。

初回は過去データで事前学習、以降は24時間ごとに再学習。
"""
import logging
import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

from src.strategy import BaseBot
from src.indicators import (
    rsi, ema, bollinger_bands, atr, adx,
    volatility, volume_weighted_momentum, obv, sma,
)

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    logger.warning("LightGBM がインストールされていません。Bot #09 は無効です。")


class BotMLGate(BaseBot):
    """LightGBM ベースの ML ゲート戦略"""

    def __init__(self, bot_config: dict):
        super().__init__(bot_config)
        p = self.params
        self.model_dir = Path(p.get("model_dir", "models"))
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.models = {}  # {symbol: lgb.Booster}
        self.last_train_time = {}
        self._load_models()

    def _model_path(self, symbol: str) -> Path:
        safe_name = symbol.replace("/", "_")
        return self.model_dir / f"ml_gate_{safe_name}.pkl"

    def _load_models(self):
        """保存済みモデルをロードする。"""
        for symbol in self.symbols:
            path = self._model_path(symbol)
            if path.exists():
                try:
                    with open(path, "rb") as f:
                        self.models[symbol] = pickle.load(f)
                    logger.info(f"[{self.name}] {symbol} モデルをロード")
                except Exception as e:
                    logger.warning(f"[{self.name}] モデルロード失敗 ({symbol}): {e}")

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """特徴量DataFrame を構築する。"""
        close = df["close"].astype(float)
        features = pd.DataFrame(index=df.index)

        # 基本
        features["rsi_14"] = rsi(close, 14)
        features["ema_12"] = ema(close, 12) / close - 1  # EMA乖離率
        features["ema_48"] = ema(close, 48) / close - 1

        # BB
        _, _, _, bb_bw, bb_z = bollinger_bands(close, 20, 2.0)
        features["bb_bandwidth"] = bb_bw
        features["bb_zscore"] = bb_z

        # ATR (正規化)
        atr_vals = atr(df, 14)
        features["atr_pct"] = atr_vals / close

        # ADX
        adx_vals, plus_di, minus_di = adx(df, 14)
        features["adx"] = adx_vals
        features["di_diff"] = plus_di - minus_di

        # Volatility
        features["volatility"] = volatility(close, 24)

        # OBV slope
        obv_vals = obv(df)
        obv_ema = ema(obv_vals, 12)
        features["obv_slope"] = (obv_vals - obv_ema) / obv_ema.abs().replace(0, np.nan)

        # Volume z-score
        vol = df["volume"].astype(float)
        vol_mean = sma(vol, 48)
        vol_std = vol.rolling(window=48).std()
        features["vol_zscore"] = (vol - vol_mean) / vol_std.replace(0, np.nan)

        # Returns
        features["ret_1"] = close.pct_change(1)
        features["ret_6"] = close.pct_change(6)
        features["ret_12"] = close.pct_change(12)

        return features

    def train(self, df: pd.DataFrame, symbol: str):
        """モデルを再学習する。"""
        if not HAS_LGB:
            return

        p = self.params
        horizon = p["prediction_horizon"]

        features = self._build_features(df)
        # ターゲット: N本先リターン
        target = df["close"].astype(float).pct_change(horizon).shift(-horizon)

        # 有効行のみ
        valid = features.dropna().index.intersection(target.dropna().index)
        if len(valid) < p["min_train_samples"]:
            logger.warning(f"[{self.name}][{symbol}] 学習データ不足: {len(valid)} < {p['min_train_samples']}")
            return

        X = features.loc[valid]
        y = target.loc[valid]

        # 学習/検証分割
        split = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split], X.iloc[split:]
        y_train, y_val = y.iloc[:split], y.iloc[split:]

        train_set = lgb.Dataset(X_train, label=y_train)
        val_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

        params = {
            "objective": "regression",
            "metric": "mse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 20,
            "verbose": -1,
            "force_row_wise": True,
        }

        model = lgb.train(
            params, train_set,
            valid_sets=[val_set],
            num_boost_round=200,
            callbacks=[lgb.early_stopping(20, verbose=False)],
        )

        self.models[symbol] = model
        self.last_train_time[symbol] = datetime.now(timezone.utc)

        # 保存
        with open(self._model_path(symbol), "wb") as f:
            pickle.dump(model, f)

        logger.info(f"[{self.name}][{symbol}] モデル学習完了 (データ={len(valid)}件)")

    def _needs_retrain(self, symbol: str) -> bool:
        """再学習が必要か判定する。"""
        if symbol not in self.models:
            return True
        if symbol not in self.last_train_time:
            return True

        hours_since = (datetime.now(timezone.utc) - self.last_train_time[symbol]).total_seconds() / 3600
        return hours_since >= self.params["retrain_interval_hours"]

    def compute_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        if not HAS_LGB:
            return self._hold_signal("LightGBM未インストール")

        # 再学習チェック
        if self._needs_retrain(symbol):
            train_window = self.params["train_window_bars"]
            train_df = df.tail(train_window) if len(df) > train_window else df
            self.train(train_df, symbol)

        if symbol not in self.models:
            return self._hold_signal("モデル未学習")

        # 予測
        features = self._build_features(df)
        last_features = features.iloc[[-1]].dropna(axis=1)

        if last_features.empty:
            return self._hold_signal("特徴量計算不可")

        try:
            prediction = self.models[symbol].predict(last_features)[0]
        except Exception as e:
            logger.warning(f"[{self.name}][{symbol}] 予測エラー: {e}")
            return self._hold_signal(f"予測エラー: {e}")

        # 予測値 → ポジション
        if prediction > 0.002:
            pos = min(0.8, prediction * 100)  # 2%以上の上昇予測で最大0.8
            return {
                "target_position": pos,
                "confidence": min(0.8, abs(prediction) * 50),
                "reason": f"ML予測: +{prediction:.4f} → ロング (pos={pos:.2f})",
                "stop_loss": None,
            }
        elif prediction < -0.001:
            return {
                "target_position": 0.0,
                "confidence": min(0.6, abs(prediction) * 50),
                "reason": f"ML予測: {prediction:.4f} → クローズ",
                "stop_loss": None,
            }
        else:
            return {
                "target_position": 0.1,
                "confidence": 0.2,
                "reason": f"ML予測中立: {prediction:.4f}",
                "stop_loss": None,
            }
