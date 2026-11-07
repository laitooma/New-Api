"""Backtest engine.

Rules that keep the numbers honest:
- signal computed at the close of day t, trade executed at the OPEN of day t+1;
- every change in position pays `cost` (fee + slippage) on the traded fraction;
- no leverage, no shorting: position is always between 0 (cash) and 1 (fully in).
"""

import numpy as np
import pandas as pd


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def run(df: pd.DataFrame, target: pd.Series, cost: float) -> pd.Series:
    """Return the daily equity curve (starts at 1.0)."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    tgt = target.reindex(df.index).fillna(0.0).to_numpy()
    eq = np.ones(len(df))
    pos = 0.0
    for t in range(1, len(df)):
        new = tgt[t - 1]  # decided at yesterday's close
        gap = o[t] / c[t - 1] - 1  # overnight move, old position
        intraday = c[t] / o[t] - 1  # open -> close, new position
        e = eq[t - 1] * (1 + pos * gap)
        e *= 1 - abs(new - pos) * cost  # trading cost at the open
        e *= 1 + new * intraday
        eq[t] = e
        pos = new
    return pd.Series(eq, index=df.index)


def metrics(eq: pd.Series, target: pd.Series, periods: int) -> dict:
    r = eq.pct_change().dropna()
    years = len(r) / periods
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(periods) if r.std() > 0 else 0.0
    t = target.reindex(eq.index).fillna(0.0)
    trades = int((t.diff().abs() > 1e-9).sum())
    monthly = eq.resample("ME").last().pct_change().dropna()
    return {
        "total_%": round(total * 100, 1),
        "annual_%": round(cagr * 100, 1),
        "max_dd_%": round(dd * 100, 1),
        "sharpe": round(sharpe, 2),
        "trades": trades,
        "exposure_%": round(t.mean() * 100, 0),
        "pos_months_%": round((monthly > 0).mean() * 100, 0)
        if len(monthly)
        else np.nan,
    }
