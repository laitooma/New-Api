"""Paper day trading, one UTC day at a time (no real money, ever).

Strategy frozen on 2026-11-07, before any of the days it will be judged on:
"cassure Asie" (Asian-session range breakout), long AND short, entry on an hourly
close outside the 00:00-06:59 UTC range from 07:00, exit at 20:00 UTC, one trade a
day per market, 0.10% cost per side. It was the only one of 32 tested
combinations positive on all 4 markets over 20 days, which is likely luck (its gain
came from shorts in a falling market). Only these future days can tell.

Run once a day after 21:00 UTC (a later run, even past midnight, records the
previous day instead, and a day is never recorded twice):
    python intraday_paper.py           # Kraken public hourly prices (no API key)
    python intraday_paper.py --csv     # replay every day of data/*_H1.csv (check)
"""

import argparse
import csv
import os
from datetime import UTC, datetime

import intraday as it
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, os.getenv("INTRADAY_STATE_DIR", "paper_intraday"))
COST = 0.001
MARKETS = {"BTC": "BTC/USD", "ETH": "ETH/USD", "GOLD": "PAXG/USD"}
CSV_FILES = {"BTC": "BTC_USD_H1.csv", "ETH": "ETH_USD_H1.csv", "GOLD": "XAU_USD_H1.csv"}


def day_result(bars: pd.DataFrame) -> dict:
    """Net result of the frozen strategy on ONE UTC day of closed hourly bars."""
    pos = it.asia_breakout(bars)
    r = it.run(bars, pos, COST, long_only=False)
    return {"pnl_%": r["total_%"], "trades": r["trades"]}


def closed_hourly(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    return df[df.index + pd.Timedelta(hours=1) <= now]


def fetch_kraken(symbol: str) -> pd.DataFrame:
    import ccxt

    ex = ccxt.kraken({"enableRateLimit": True})
    rows = ex.fetch_ohlcv(symbol, "1h", limit=72)
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "vol"])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def record(day, market: str, res: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "days.csv")
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            seen = {(r["date"], r["market"]) for r in csv.DictReader(f)}
    if (str(day), market) in seen:
        return
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["date", "market", "trades", "pnl_%"])
        w.writerow([day, market, res["trades"], res["pnl_%"]])


def summary() -> None:
    path = os.path.join(OUT_DIR, "days.csv")
    if not os.path.exists(path):
        return
    d = pd.read_csv(path)
    # equal thirds of the capital, each compounding its own daily results
    eq = (
        1 + d.pivot_table(index="date", columns="market", values="pnl_%") / 100
    ).cumprod()
    total = (eq.iloc[-1].mean() - 1) * 100
    print(
        f"simulation day trading: {d['date'].nunique()} jours, "
        f"{int(d['trades'].sum())} trades, résultat {total:+.2f}% (500 -> {500 * (1 + total / 100):.2f})"
    )


def run_today() -> None:
    """Record the most recent finished trading day. After 21:00 UTC that is
    today; before (e.g. a run delayed past midnight) it is yesterday."""
    now = pd.Timestamp(datetime.now(UTC))
    today = (
        now.normalize() if now.hour >= 21 else now.normalize() - pd.Timedelta(days=1)
    )
    for name, sym in MARKETS.items():
        df = closed_hourly(fetch_kraken(sym), now)
        bars = df[df.index.normalize() == today]
        if len(bars) < 21:
            print(f"{name}: only {len(bars)} hourly bars today, skipped")
            continue
        res = day_result(bars)
        record(today.date(), name, res)
        print(f"{today.date()} {name}: {res['trades']} trade(s), {res['pnl_%']:+.2f}%")
    summary()


def replay_csv() -> None:
    global OUT_DIR
    OUT_DIR = os.path.join(HERE, "replay_intraday")
    if os.path.exists(os.path.join(OUT_DIR, "days.csv")):
        os.remove(os.path.join(OUT_DIR, "days.csv"))
    for name, f in CSV_FILES.items():
        df = it.load_h1(os.path.join(HERE, "data", f))
        for day, bars in df.groupby(df.index.normalize()):
            if len(bars) >= 21:
                record(day.date(), name, day_result(bars))
    summary()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true", help="replay local hourly CSVs")
    if ap.parse_args().csv:
        replay_csv()
    else:
        run_today()
