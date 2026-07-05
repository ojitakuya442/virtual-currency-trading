"""
2026-07-05 構成見直し(①頻度削減+②現金退避)の検証用バックテスト。

DBの価格履歴を使い、旧設定(5分足グリッド・閾値0.05・クールダウンなし・レジームなし)と
新設定(1時間足・閾値0.20・最低保有240分・下落レジーム退避)で
各botのシグナル→約定をリプレイし、取引数・コスト・グロス/ネット損益を比較する。

簡略化(結果の解釈時に注意):
- 対象は単銘柄テクニカルの6bot(01-06)。07(ペア)/08(メタ)/09(ML)/10(外部データ)は除外
  — ただし除外botも同じ執行レイヤ(閾値/クールダウン/レジーム)を通るため方向性は共通
- 銘柄ごとに独立サブ口座(初期資産を銘柄数で等分)として簡易執行
- 旧グリッドはpricesテーブルの実記録間隔(≈15分〜1時間)そのまま = 本番実行周期の近似
- bot実装コードそのものを呼ぶ(compute_signal)。ロジックの再実装はしない

usage: python scripts/backtest_restructure.py [days]
"""
import sys
import sqlite3
import pathlib

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.config import DB_PATH, BOT_CONFIGS, USD_JPY_RATE, TOTAL_COST_RATE
from src.bots.bot_01_donchian import BotDonchian
from src.bots.bot_02_ema_adx import BotEmaAdx
from src.bots.bot_03_bb_zscore import BotBBZscore
from src.bots.bot_04_vwap import BotVWAP
from src.bots.bot_05_squeeze import BotSqueeze
from src.bots.bot_06_vol_momentum import BotVolMomentum

BOTS = {
    "01_donchian": BotDonchian,
    "02_ema_adx": BotEmaAdx,
    "03_bb_zscore": BotBBZscore,
    "04_vwap": BotVWAP,
    "05_squeeze": BotSqueeze,
    "06_vol_momentum": BotVolMomentum,
}

WINDOW = 400  # compute_signal に渡す最大バー数(全botの必要期間を十分カバー)


def load_prices(symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume FROM prices "
        "WHERE symbol = ? ORDER BY timestamp",
        conn, params=(symbol,))
    conn.close()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    return df


def to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    out = (df.set_index("timestamp").sort_index()
           .resample("1h")
           .agg({"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"})
           .dropna().reset_index())
    return out


def replay(bot, df: pd.DataFrame, symbol: str, eval_start,
           threshold: float, cooldown_min: int,
           regime_sma: int | None, sub_capital: float):
    """1銘柄サブ口座の簡易リプレイ。戻り値: (trades, cost, net_pnl, gross_pnl)"""
    balance = sub_capital
    qty = 0.0
    trades = 0
    cost_paid = 0.0
    last_trade_ts = None

    sma = df["close"].rolling(regime_sma).mean() if regime_sma else None

    for i in range(len(df)):
        ts = df["timestamp"].iloc[i]
        if ts < eval_start:
            continue
        window = df.iloc[max(0, i - WINDOW + 1): i + 1].reset_index(drop=True)
        if len(window) < 60:
            continue
        try:
            sig = bot.compute_signal(window, symbol)
        except Exception:
            continue
        target = float(sig.get("target_position", 0.0) or 0.0)

        if regime_sma is not None and not pd.isna(sma.iloc[i]) \
                and df["close"].iloc[i] < sma.iloc[i]:
            target = 0.0  # 下落レジーム退避

        price_jpy = df["close"].iloc[i] * USD_JPY_RATE
        total = balance + qty * price_jpy
        cur_pos = (qty * price_jpy) / total if total > 0 else 0.0
        delta = target - cur_pos
        if abs(delta) < threshold:
            continue
        if cooldown_min and last_trade_ts is not None \
                and (ts - last_trade_ts).total_seconds() / 60 < cooldown_min:
            continue

        if delta > 0:
            amount = min(total * delta, balance)
            if amount <= 0:
                continue
            eff = price_jpy * (1 + TOTAL_COST_RATE)
            qty += amount / eff
            balance -= amount
            cost_paid += amount / eff * price_jpy * TOTAL_COST_RATE
        else:
            sell_qty = qty * min(1.0, -delta / cur_pos) if cur_pos > 0 else 0.0
            if sell_qty <= 0:
                continue
            eff = price_jpy * (1 - TOTAL_COST_RATE)
            balance += sell_qty * eff
            qty -= sell_qty
            cost_paid += sell_qty * price_jpy * TOTAL_COST_RATE
        trades += 1
        last_trade_ts = ts

    final_price = df["close"].iloc[-1] * USD_JPY_RATE
    net = balance + qty * final_price - sub_capital
    return trades, cost_paid, net, net + cost_paid


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(f"=== 構成見直しバックテスト (直近{days}日評価 / 対象: 01-06) ===")

    raw = {}
    hourly = {}
    for sym in ("BTC/USD", "ETH/USD", "SOL/USD"):
        raw[sym] = load_prices(sym)
        hourly[sym] = to_hourly(raw[sym])
    eval_start = raw["BTC/USD"]["timestamp"].max() - pd.Timedelta(days=days)

    header = f"{'bot':<16}{'旧:取引':>8}{'旧:コスト':>10}{'旧:純損益':>10}" \
             f"{'新:取引':>8}{'新:コスト':>10}{'新:純損益':>10}"
    print(header)
    totals = [0, 0.0, 0.0, 0, 0.0, 0.0]
    for name, cls in BOTS.items():
        cfg = BOT_CONFIGS[name]
        syms = cfg["symbols"]
        sub = 50_000 / len(syms)
        old = [0, 0.0, 0.0]
        new = [0, 0.0, 0.0]
        for sym in syms:
            t, c, n, _ = replay(cls(cfg), raw[sym], sym, eval_start,
                                threshold=0.05, cooldown_min=0,
                                regime_sma=None, sub_capital=sub)
            old[0] += t; old[1] += c; old[2] += n
            t, c, n, _ = replay(cls(cfg), hourly[sym], sym, eval_start,
                                threshold=0.20, cooldown_min=240,
                                regime_sma=200, sub_capital=sub)
            new[0] += t; new[1] += c; new[2] += n
        print(f"{name:<16}{old[0]:>8}{old[1]:>10.0f}{old[2]:>10.0f}"
              f"{new[0]:>8}{new[1]:>10.0f}{new[2]:>10.0f}")
        for i in range(3):
            totals[i] += old[i]
            totals[3 + i] += new[i]
    print("-" * len(header))
    print(f"{'合計':<16}{totals[0]:>8}{totals[1]:>10.0f}{totals[2]:>10.0f}"
          f"{totals[3]:>8}{totals[4]:>10.0f}{totals[5]:>10.0f}")


if __name__ == "__main__":
    main()
