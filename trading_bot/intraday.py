"""Day-trading research on hourly candles.

Same honesty rules as the daily engine:
- a position is decided at the close of an hourly bar and applied to the NEXT bar;
- every change of position pays `cost` (fee + spread/slippage) on the traded size;
- every position is closed at the end of the UTC day (FLAT_HOUR), so nothing is
  held overnight: that is what makes it day trading;
- the last bar of the file may still be forming, so it is dropped.

Positions are -1 (short), 0 (flat) or +1 (long). `long_only=True` removes shorts
(a spot crypto account cannot short).
"""

import numpy as np
import pandas as pd

FLAT_HOUR = 23  # close everything at the end of the 23:00 UTC bar


def load_h1(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float).iloc[:-1]


def _flat_at_day_end(pos: np.ndarray, idx: pd.DatetimeIndex) -> np.ndarray:
    """No position may be carried past the end of the day."""
    pos = pos.copy()
    hours = idx.hour.to_numpy()
    days = idx.normalize()
    last_of_day = np.r_[days[1:] != days[:-1], True]
    pos[(hours >= FLAT_HOUR) | last_of_day] = 0.0
    return pos


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ------------------------------------------------------------------ strategies
def breakout(df: pd.DataFrame, entry: int = 12, exit_: int = 6) -> np.ndarray:
    """Buy a close above the previous `entry` hours' high (sell below the low),
    exit on a close back through the previous `exit_` hours' opposite extreme."""
    hi = df["high"].rolling(entry).max().shift(1).to_numpy()
    lo = df["low"].rolling(entry).min().shift(1).to_numpy()
    xlo = df["low"].rolling(exit_).min().shift(1).to_numpy()
    xhi = df["high"].rolling(exit_).max().shift(1).to_numpy()
    c = df["close"].to_numpy()
    pos = np.zeros(len(df))
    p = 0.0
    for i in range(len(df)):
        if p == 0:
            if c[i] > hi[i]:
                p = 1.0
            elif c[i] < lo[i]:
                p = -1.0
        elif (p == 1 and c[i] < xlo[i]) or (p == -1 and c[i] > xhi[i]):
            p = 0.0
        if df.index[i].hour >= FLAT_HOUR:
            p = 0.0
        pos[i] = p
    return pos


def ema_cross(df: pd.DataFrame, fast: int = 8, slow: int = 21) -> np.ndarray:
    f, s = _ema(df["close"], fast), _ema(df["close"], slow)
    return np.where(f > s, 1.0, -1.0)


def rsi_revert(
    df: pd.DataFrame, n: int = 2, lo: float = 10, hi: float = 90
) -> np.ndarray:
    """Fade short-term extremes in the direction of the hourly trend (EMA 50)."""
    r = _rsi(df["close"], n).to_numpy()
    trend_up = (df["close"] > _ema(df["close"], 50)).to_numpy()
    pos = np.zeros(len(df))
    p = 0.0
    for i in range(len(df)):
        if p == 0:
            if r[i] < lo and trend_up[i]:
                p = 1.0
            elif r[i] > hi and not trend_up[i]:
                p = -1.0
        elif (p == 1 and r[i] > 70) or (p == -1 and r[i] < 30):
            p = 0.0
        if df.index[i].hour >= FLAT_HOUR:
            p = 0.0
        pos[i] = p
    return pos


def asia_breakout(df: pd.DataFrame, end_hour: int = 20) -> np.ndarray:
    """Asian-session range (00:00-06:59 UTC): trade a close outside it from
    07:00, hold until `end_hour` UTC. One trade per day."""
    pos = np.zeros(len(df))
    for _day, g in df.groupby(df.index.normalize()):
        asia = g[g.index.hour < 7]
        if len(asia) < 5:
            continue
        rh, rl = asia["high"].max(), asia["low"].min()
        p, done = 0.0, False
        for ts, row in g.iterrows():
            i = df.index.get_loc(ts)
            if ts.hour >= end_hour:
                p = 0.0
            elif ts.hour >= 7 and p == 0 and not done:
                if row["close"] > rh:
                    p, done = 1.0, True
                elif row["close"] < rl:
                    p, done = -1.0, True
            pos[i] = p
    return pos


STRATEGIES = {
    "breakout 12h": breakout,
    "ema 8/21": ema_cross,
    "rsi2 retour": rsi_revert,
    "cassure Asie": asia_breakout,
}


# ------------------------------------------------------------------ engine
def run(df: pd.DataFrame, pos: np.ndarray, cost: float, long_only: bool) -> dict:
    pos = np.asarray(pos, dtype=float)
    if long_only:
        pos = np.clip(pos, 0, 1)
    pos = _flat_at_day_end(pos, df.index)
    ret = df["close"].pct_change().fillna(0).to_numpy()
    held = np.r_[0.0, pos[:-1]]  # decided at bar t-1's close, earns bar t
    turnover = np.abs(np.diff(np.r_[0.0, held]))
    pnl = held * ret - turnover * cost
    eq = pd.Series(np.cumprod(1 + pnl), index=df.index)
    daily = eq.resample("D").last().dropna().pct_change().dropna()
    traded_days = pd.Series(np.abs(held), index=df.index).resample("D").sum()
    daily = daily[traded_days.reindex(daily.index).fillna(0) > 0]
    entries = int(((held != 0) & (np.r_[0.0, held[:-1]] != held)).sum())
    return {
        "total_%": round((eq.iloc[-1] - 1) * 100, 2),
        "max_dd_%": round((eq / eq.cummax() - 1).min() * 100, 2),
        "trades": entries,
        "jours_tradés": len(daily),
        "jours_gagnants_%": round((daily > 0).mean() * 100, 0) if len(daily) else 0,
        "frais_payés_%": round(turnover.sum() * cost * 100, 2),
    }
