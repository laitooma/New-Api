"""Paper day trading, one UTC day at a time (no real money, ever).

Strategy frozen on 2026-11-07, before any of the days it will be judged on:
"cassure Asie" (Asian-session range breakout), long AND short, entry on an hourly
close outside the 00:00-06:59 UTC range from 07:00, exit at 20:00 UTC, one trade a
day per market, 0.10% cost per side. It was the only one of 32 tested
combinations positive on all 4 markets over 20 days, which is likely luck (its gain
came from shorts in a falling market). Only these future days can tell.

Run after 21:00 UTC. Every run records all finished days not recorded yet
(GitHub sometimes skips scheduled runs), and a day is never recorded twice:
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
# The rules were frozen on 2026-11-07 around 12:20 UTC, after hourly prices up
# to 12:00 that day had been seen. Days up to the 7th are therefore in-sample;
# only days from FIRST_DAY on count as an honest, out-of-sample test.
FIRST_DAY = pd.Timestamp("2026-11-08", tz="UTC")
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
    rows = ex.fetch_ohlcv(symbol, "1h", limit=720)  # ~30 days: room to catch up
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
    # a market with no row on a day earned 0% that day (it must not vanish
    # from the total, which is what a missing value on the last day did)
    daily = d.pivot_table(index="date", columns="market", values="pnl_%")
    eq = (1 + daily.reindex(columns=list(MARKETS)).fillna(0.0) / 100).cumprod()
    total = (eq.iloc[-1].mean() - 1) * 100
    print(
        f"simulation day trading: {d['date'].nunique()} jours, "
        f"{int(d['trades'].sum())} trades, résultat {total:+.2f}% (500 -> {500 * (1 + total / 100):.2f})"
    )


def is_out_of_sample(day: pd.Timestamp) -> bool:
    return day.normalize() >= FIRST_DAY


def finished_days(now: pd.Timestamp) -> list:
    """Days from FIRST_DAY whose trading is over (20:00 bar closed at 21:00 UTC),
    oldest first. Kraken's 720 hourly bars cover the last ~30 of them."""
    last = now.normalize() if now.hour >= 21 else now.normalize() - pd.Timedelta(days=1)
    first = max(FIRST_DAY, last - pd.Timedelta(days=28))
    return list(pd.date_range(first, last, freq="D")) if last >= FIRST_DAY else []


def recorded() -> set:
    path = os.path.join(OUT_DIR, "days.csv")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {(r["date"], r["market"]) for r in csv.DictReader(f)}


def run_today() -> None:
    """Record every finished out-of-sample day not recorded yet, so a run that
    GitHub delayed or skipped is caught up by the next one. Never twice."""
    now = pd.Timestamp(datetime.now(UTC))
    days = finished_days(now)
    if not days:
        print(f"nothing to record before {FIRST_DAY.date()} (earlier days were seen)")
        return
    done = recorded()
    for name, sym in MARKETS.items():
        todo = [d for d in days if (str(d.date()), name) not in done]
        if not todo:
            continue
        df = closed_hourly(fetch_kraken(sym), now)
        for day in todo:
            bars = df[df.index.normalize() == day]
            if len(bars) < 21:
                print(f"{day.date()} {name}: only {len(bars)} hourly bars, skipped")
                continue
            res = day_result(bars)
            record(day.date(), name, res)
            print(
                f"{day.date()} {name}: {res['trades']} trade(s), {res['pnl_%']:+.2f}%"
            )
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
