"""Trading signals. Each function takes a daily DataFrame (open, high, low, close)
and returns a target position in [0, 1] decided at the close of each day.
The position is only applied from the next day's open (see backtest.py),
so a signal never uses information it could not have had."""

import numpy as np
import pandas as pd


def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index)


def sma_trend(df: pd.DataFrame, n: int = 50) -> pd.Series:
    """Long when close is above its n-day simple moving average, else cash."""
    sma = df["close"].rolling(n).mean()
    return (df["close"] > sma).astype(float).where(sma.notna(), 0.0)


def ema_cross(df: pd.DataFrame, fast: int = 20, slow: int = 100) -> pd.Series:
    """Long when the fast EMA is above the slow EMA."""
    f = df["close"].ewm(span=fast, adjust=False).mean()
    s = df["close"].ewm(span=slow, adjust=False).mean()
    pos = (f > s).astype(float)
    pos.iloc[:slow] = 0.0
    return pos


def donchian(df: pd.DataFrame, entry: int = 20, exit: int = 10) -> pd.Series:
    """Buy a close above the previous `entry`-day high, sell a close below the
    previous `exit`-day low (classic turtle-style breakout, long only)."""
    hi = df["high"].rolling(entry).max().shift(1)
    lo = df["low"].rolling(exit).min().shift(1)
    pos = np.zeros(len(df))
    inpos = 0.0
    for i, (c, h, l) in enumerate(zip(df["close"], hi, lo)):
        if inpos == 0.0 and not np.isnan(h) and c > h:
            inpos = 1.0
        elif inpos == 1.0 and not np.isnan(l) and c < l:
            inpos = 0.0
        pos[i] = inpos
    return pd.Series(pos, index=df.index)


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def rsi_reversion(df: pd.DataFrame, n: int = 2, buy_below: float = 10,
                  sell_above: float = 70, trend: int = 100) -> pd.Series:
    """Short-term mean reversion: buy a deep RSI dip inside an uptrend
    (close above the `trend`-day SMA), exit when RSI recovers."""
    r = rsi(df["close"], n)
    sma = df["close"].rolling(trend).mean()
    pos = np.zeros(len(df))
    inpos = 0.0
    for i in range(len(df)):
        if inpos == 0.0 and r.iloc[i] < buy_below and df["close"].iloc[i] > sma.iloc[i]:
            inpos = 1.0
        elif inpos == 1.0 and (r.iloc[i] > sell_above or df["close"].iloc[i] < sma.iloc[i]):
            inpos = 0.0
        pos[i] = inpos
    return pd.Series(pos, index=df.index)


def vol_target(df: pd.DataFrame, base: pd.Series, target_ann_vol: float = 0.40,
               lookback: int = 20, periods: int = 365) -> pd.Series:
    """Scale a 0/1 signal down when recent volatility is high, never above 1
    (no leverage). Keeps risk roughly constant across calm and wild markets."""
    rets = df["close"].pct_change()
    vol = rets.rolling(lookback).std() * np.sqrt(periods)
    scale = (target_ann_vol / vol).clip(upper=1.0).fillna(0.0)
    return base * scale


def sma_ensemble(df: pd.DataFrame, lengths=(30, 40, 50, 60, 70, 80, 100)) -> pd.Series:
    """Average of several SMA trend filters. Position steps between 0 and 1
    (e.g. 4 of 7 filters bullish -> 57% invested). Avoids betting the whole
    result on one lucky moving-average length."""
    return sum(sma_trend(df, n) for n in lengths) / len(lengths)
