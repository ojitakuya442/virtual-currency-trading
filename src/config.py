"""
仮想通貨自動売買Bot - 設定ファイル
10bot・target_position アーキテクチャ対応版
"""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 対象銘柄
# ============================================================
SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
USD_JPY_TICKER = "USD/JPY"
FIXED_USD_JPY_RATE = 150.0  # PnL計算用の固定レート（為替変動係数を排除するため）

# ============================================================
# 取引所設定
# ============================================================
EXCHANGE_ID = "kraken"

# ============================================================
# 運用パラメータ
# ============================================================
INITIAL_BALANCE = 50_000         # 各ボットの初期仮想資産（円）
USD_JPY_RATE = 150.0            # USD→JPY変換レート（概算）
TRADE_FEE_RATE = 0.001          # 取引手数料 (0.1% = taker)
SLIPPAGE_RATE = 0.0005          # スリッページ (0.05%)
TOTAL_COST_RATE = TRADE_FEE_RATE + SLIPPAGE_RATE  # 合計 0.15%

# ============================================================
# データ取得設定
# ============================================================
INTERVAL = "5m"
INTERVAL_MINUTES = 5
HISTORICAL_DAYS = 30

# ============================================================
# エラーハンドリング
# ============================================================
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1
ANOMALY_THRESHOLD = 0.5

# ============================================================
# リスク管理（共通ルール）
# ============================================================
CIRCUIT_BREAKER_THRESHOLD = 0.20   # 初期資産の20%減少で自動停止
DAILY_LOSS_LIMIT = 0.05            # 日次損失上限 (5%)
POSITION_CHANGE_THRESHOLD = 0.05   # ポジション変更最小閾値
MAX_POSITION = 1.0                 # 最大ポジション (= 資産100%)
MIN_POSITION = 0.0                 # 最小ポジション (ロングのみ)

# ============================================================
# 通知設定
# ============================================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")
DAILY_REPORT_HOUR = 21

# ============================================================
# データベース
# ============================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "trading_bot.db"

# ============================================================
# 10 Bot 定義
# ============================================================
BOT_CONFIGS = {
    "01_donchian": {
        "name": "01_donchian",
        "description": "Donchian ブレイクアウト (トレンド追随)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "channel_period": 48,       # Donchian上限/下限の計算期間
            "atr_period": 14,
            "atr_trail_k": 2.0,         # ATR×k のトレーリングストップ
        },
    },
    "02_ema_adx": {
        "name": "02_ema_adx",
        "description": "EMAトレンド + ADXフィルタ (ダマシ回避)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "ema_short": 12,
            "ema_long": 48,
            "adx_period": 14,
            "adx_threshold": 25,        # ADXがこの値以上でトレンド判定
        },
    },
    "03_bb_zscore": {
        "name": "03_bb_zscore",
        "description": "ボリンジャー z-score 平均回帰 (レンジ取り)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "zscore_entry": 2.0,        # z-score閾値
            "rsi_period": 14,
            "rsi_confirm": 30,          # RSI確認ライン
            "max_hold_bars": 48,        # 最大保有本数（4時間）
            "adx_period": 14,
            "adx_pause_threshold": 30,  # ADX高→トレンド中は停止
        },
    },
    "04_vwap": {
        "name": "04_vwap",
        "description": "VWAPアンカー (回帰/順張り切替)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "vwap_period": 48,          # ローリングVWAP期間
            "deviation_threshold": 0.01, # 乖離率閾値 (1%)
            "volume_surge_k": 1.5,      # 出来高急増判定倍率
        },
    },
    "05_squeeze": {
        "name": "05_squeeze",
        "description": "ボラ収縮→拡大ブレイク (爆発待ち)",
        "symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "bandwidth_low_pct": 0.25,  # BW下位25%で収縮判定
            "atr_period": 14,
            "atr_trail_k": 1.5,
            "lookback": 24,             # 収縮判定のルックバック
        },
    },
    "06_vol_momentum": {
        "name": "06_vol_momentum",
        "description": "出来高×リターンモメンタム",
        "symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "params": {
            "momentum_period": 12,      # モメンタム算出期間
            "volume_zscore_period": 48,  # 出来高z-scoreの期間
            "obv_sma_period": 12,
            "threshold": 0.5,           # シグナル閾値
        },
    },
    "07_pair_trade": {
        "name": "07_pair_trade",
        "description": "ペアトレ BTC-ETH (相対価格の歪み取り)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "spread_period": 48,        # スプレッドの平均算出期間
            "zscore_entry": 2.0,        # エントリーz-score
            "zscore_exit": 0.5,         # エグジットz-score
            "zscore_stop": 3.5,         # 損切りz-score
        },
    },
    "08_regime": {
        "name": "08_regime",
        "description": "レジーム判定→戦略切替 (メタbot)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "volatility_window": 24,
            "trend_window": 48,
            "n_regimes": 3,             # Trend / Range / HighVol
        },
    },
    "09_ml_gate": {
        "name": "09_ml_gate",
        "description": "MLゲート (LightGBM フィルタ)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "retrain_interval_hours": 24,   # 再学習間隔
            "train_window_bars": 4032,      # 学習窓 (14日×288本/日)
            "min_train_samples": 2000,
            "prediction_horizon": 6,        # 予測先行き本数 (30分)
            "model_dir": "models",
        },
    },
    "10_deriv": {
        "name": "10_deriv",
        "description": "デリバ情報併用 (Funding/OI環境変数)",
        "symbols": ["BTC/USD", "ETH/USD"],
        "params": {
            "funding_extreme_pct": 0.01,   # Funding rate過熱閾値 (1%)
            "oi_change_threshold": 0.10,   # OI変動率閾値 (10%)
            "cooldown_bars": 6,            # 過熱後のクールダウン本数
        },
    },
}

BOT_NAMES = list(BOT_CONFIGS.keys())
