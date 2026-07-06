"""
日足×長期データのエッジ検証スイート (data/research.db が前提)。

H1 トレンドフォロー (ロングのみ・日足):
  - SMA cross 50/200, 20/100
  - Donchian 55日ブレイク入り/20日安値出 (タートル型)
  - TSMOM: 90日リターン>0でロング (週次判定)
H3 リバランス・プレミアム: 50%現金/50%現物、乖離±10ptで戻す
H2 funding キャリー: 現物ロング+perpショート (市場中立、funding受取)

共通: コスト0.15%/片道 (キャリーは4レッグ)、シグナルは終値確定後→翌日反映
(ルックアヘッド防止)。期間: IS(〜2024-12-31) / OOS(2025-01-01〜) / 全期間。

usage: python scripts/backtest_daily.py
"""
import sys
import sqlite3
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "research.db"
COST = 0.0015
# データがKraken 720日(2024-07〜)のみとなったため分割を調整 (2026-07-06、結果を見る前に確定):
# IS = 2024-07〜2025-08 (後期強気+レンジ) / OOS = 2025-09〜 (2026暴落を含む)
OOS_START = "2025-09-01"


def load_daily(symbol_usdt: str) -> pd.Series:
    """binance優先、無ければkraken(USD建てシンボルに変換)で読む。"""
    conn = sqlite3.connect(str(DB))
    sym_usd = symbol_usdt.replace("/USDT", "/USD")
    df = pd.DataFrame()
    for source, s in (("yahoo", sym_usd), ("binance", symbol_usdt), ("kraken", sym_usd)):
        df = pd.read_sql_query(
            "SELECT date, close FROM daily_prices WHERE source=? AND symbol=? ORDER BY date",
            conn, params=(source, s))
        if not df.empty:
            break
    conn.close()
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float)
    return s[~s.index.duplicated()]


def equity_from_position(close: pd.Series, pos: pd.Series) -> pd.Series:
    """pos[t](その日の終値で決定) を翌日リターンに適用。コストはposの変化量に比例。"""
    ret = close.pct_change().fillna(0.0)
    strat_ret = pos.shift(1).fillna(0.0) * ret - pos.diff().abs().fillna(pos.abs()) * COST
    return (1 + strat_ret).cumprod()


def metrics(eq: pd.Series, pos: pd.Series, label: str) -> dict:
    eq = eq.dropna()
    if len(eq) < 30:
        return {"strategy": label, "note": "データ不足"}
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    dr = eq.pct_change().dropna()
    sharpe = dr.mean() / dr.std() * np.sqrt(365) if dr.std() > 0 else np.nan
    trades = int((pos.diff().abs() > 1e-9).sum())
    expo = float((pos.shift(1).fillna(0) != 0).mean())
    return {"strategy": label, "total": total, "cagr": cagr, "maxdd": dd,
            "sharpe": sharpe, "trades": trades, "exposure": expo}


def sma_cross(close, fast, slow):
    f, s = close.rolling(fast).mean(), close.rolling(slow).mean()
    return ((f > s) & f.notna() & s.notna()).astype(float)


def donchian(close, entry_n=55, exit_n=20):
    hi = close.rolling(entry_n).max().shift(1)
    lo = close.rolling(exit_n).min().shift(1)
    pos = pd.Series(0.0, index=close.index)
    holding = False
    for i in range(len(close)):
        if not holding and not np.isnan(hi.iloc[i]) and close.iloc[i] > hi.iloc[i]:
            holding = True
        elif holding and not np.isnan(lo.iloc[i]) and close.iloc[i] < lo.iloc[i]:
            holding = False
        pos.iloc[i] = 1.0 if holding else 0.0
    return pos


def tsmom(close, lookback=90):
    mom = close.pct_change(lookback)
    raw = (mom > 0).astype(float)
    # 週次判定 (金曜の判定を翌週まで維持) で回転を抑制
    weekly = raw.resample("W-FRI").last().reindex(close.index, method="ffill").fillna(0.0)
    return weekly


def rebalance_5050(close, band=0.10):
    """50%現金/50%現物、ウェイトが0.5±bandを外れたら0.5に戻す。equityを直接返す。"""
    cash, qty = 0.5, 0.5 / close.iloc[0]
    eq = []
    n_reb = 0
    for p in close:
        total = cash + qty * p
        w = qty * p / total
        if abs(w - 0.5) > band:
            target_val = total * 0.5
            trade_val = abs(qty * p - target_val)
            qty = target_val / p
            cash = total - target_val - trade_val * COST
            n_reb += 1
        eq.append(cash + qty * p)
    s = pd.Series(eq, index=close.index)
    return s / s.iloc[0], n_reb


def carry_report():
    conn = sqlite3.connect(str(DB))
    df = pd.read_sql_query(
        "SELECT source, symbol, timestamp, rate FROM funding_rates ORDER BY timestamp", conn)
    conn.close()
    if df.empty:
        print("\n== H2: funding キャリー == データなし (取得失敗?)")
        return
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    print(f"\n== H2: funding キャリー (現物ロング+perpショートで funding を受け取る) ==")
    for (source, sym), g in df.groupby(["source", "symbol"]):
        g = g.set_index("timestamp")["rate"].sort_index()
        # 支払周期を実データから推定して年率化 (取引所により1h/8h等が異なる)
        step = g.index.to_series().diff().median()
        per_year = pd.Timedelta(days=365) / step if step and step.total_seconds() > 0 else 365 * 3
        ann = g.groupby(g.index.year).mean() * per_year * 100
        pos_share = (g > 0).mean() * 100
        print(f"  [{source}] {sym} ({g.index[0]:%Y-%m}〜{g.index[-1]:%Y-%m}, 周期≈{step}): "
              f"年率平均funding {dict(ann.round(1))}% / 正の期間 {pos_share:.0f}%")
        # 簡易キャリーシム: fundingの30期間MAが正の間だけ建玉。切替時に2レッグ×0.15%
        ma = g.rolling(30).mean()
        on = (ma > 0).astype(int)
        pnl = (g * on.shift(1).fillna(0)).cumsum() - on.diff().abs().fillna(on).cumsum() * (2 * COST)
        yrs = (g.index[-1] - g.index[0]).days / 365.25
        if yrs > 0:
            print(f"    キャリー戦略 累計 {pnl.iloc[-1]*100:+.1f}% ({yrs:.1f}年, 年率 {pnl.iloc[-1]/yrs*100:+.1f}%), 建玉率 {on.mean()*100:.0f}%")


def fmt(m):
    if "note" in m:
        return f"    {m['strategy']:<18}{m['note']}"
    return (f"    {m['strategy']:<18}計{m['total']*100:>+8.1f}%  年率{m['cagr']*100:>+7.1f}%  "
            f"最大DD{m['maxdd']*100:>7.1f}%  Sharpe{m['sharpe']:>5.2f}  "
            f"取引{m['trades']:>4}  建玉率{m['exposure']*100:>4.0f}%")


def main():
    if not DB.exists():
        print("data/research.db がありません。先に research_data ワークフローを実行してください。")
        sys.exit(1)

    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        close_full = load_daily(sym)
        if close_full.empty:
            print(f"{sym}: データなし")
            continue
        print(f"\n===== {sym} ({close_full.index[0]:%Y-%m-%d}〜{close_full.index[-1]:%Y-%m-%d}) =====")
        # 指標・ポジションは全系列で一度だけ計算し(ウォームアップを共有)、期間はスライスで評価
        pos_all = {
            "SMA50/200": sma_cross(close_full, 50, 200),
            "SMA20/100": sma_cross(close_full, 20, 100),
            "Donchian55/20": donchian(close_full),
            "TSMOM90d": tsmom(close_full),
        }
        for label, sl in (("IS(〜2025-08)", slice(None, OOS_START)),
                          ("OOS(2025-09〜)", slice(OOS_START, None)),
                          ("全期間", slice(None, None))):
            close = close_full.loc[sl]
            if len(close) < 150:
                continue
            print(f"  -- {label} ({close.index[0]:%Y-%m}〜{close.index[-1]:%Y-%m}) --")
            bh = pd.Series(1.0, index=close.index)
            print(fmt(metrics(equity_from_position(close, bh), bh, "Buy&Hold")))
            for name, pos_full in pos_all.items():
                pos = pos_full.loc[sl]
                print(fmt(metrics(equity_from_position(close, pos), pos, name)))
            eq, n = rebalance_5050(close)
            m = metrics(eq, pd.Series(0.5, index=close.index), "50/50リバランス")
            m["trades"] = n
            print(fmt(m))

    carry_report()


if __name__ == "__main__":
    main()
