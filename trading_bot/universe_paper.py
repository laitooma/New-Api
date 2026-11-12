"""Paper test of the daily trend filter on 7 MORE markets (no real money, ever).

A separate simulation, kept apart from the bot's own (BTC, ETH, gold) so that
neither test disturbs the other. Rules frozen on 2026-11-12, before any of the
days it will be judged on: the bot's SMA ensemble, unchanged, on Nasdaq 100,
S&P 500, DAX, oil, silver, EUR/USD and USD/JPY; one seventh of the capital per
market, each compounding its own results; 0.20% cost per side.

It is the backtest engine run on live prices: the position is decided at a
day's close and applied from the next open. Only closed days from FIRST_DAY on
are recorded, each once, never rewritten; a missed run is caught up by the
next one. These markets cannot be traded on a crypto exchange: this measures
the strategy, not something the bot could do with 500 EUR today.

    python universe_paper.py           # Yahoo Finance daily prices (no API key)
    python universe_paper.py --csv     # replay the local data/*_D.csv (check)
"""

import argparse
import csv
import os
import sys

import backtest as bt
import bot
import pandas as pd
import strategies as st

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, os.getenv("UNIVERSE_STATE_DIR", "paper_universe"))
COST = 0.002
CAPITAL = 500.0
# Rules frozen on 2026-11-12: that day's prices had been seen, so only days
# from the 13th on count as an honest, out-of-sample test.
FIRST_DAY = pd.Timestamp("2026-11-13", tz="UTC")
MARKETS = {  # name: (Yahoo ticker, local CSV used by --csv)
    "NASDAQ": ("^NDX", "NAS100_USD_D.csv"),
    "SP500": ("^GSPC", "SPX500_USD_D.csv"),
    "DAX": ("^GDAXI", "DE30_EUR_D.csv"),
    "PETROLE": ("CL=F", "WTICO_USD_D.csv"),
    "ARGENT": ("SI=F", "XAG_USD_D.csv"),
    "EURUSD": ("EURUSD=X", "EUR_USD_D.csv"),
    "USDJPY": ("JPY=X", "USD_JPY_D.csv"),
}
FIELDS = ["date", "market", "position_%", "pnl_%"]


def day_rows(df: pd.DataFrame, first_day: pd.Timestamp) -> list:
    """One row per closed candle from `first_day` on: the position held that
    day (decided at the previous close) and the day's net result. The test
    starts flat: a position already signalled before `first_day` is bought at
    the first recorded open and pays its cost, like any other entry."""
    days = df.index.normalize()
    start = int((days < first_day).sum())  # first candle of the test
    if start == 0 or start >= len(df):
        return []
    target = st.sma_ensemble(df)
    target.iloc[: start - 1] = 0.0  # flat before the test starts
    eq = bt.run(df, target, COST)
    return [
        {
            "date": str(days[i].date()),
            "position_%": round(float(target.iloc[i - 1]) * 100, 1),
            "pnl_%": round(float(eq.iloc[i] / eq.iloc[i - 1] - 1) * 100, 3),
        }
        for i in range(start, len(df))
    ]


def recorded() -> set:
    path = os.path.join(OUT_DIR, "days.csv")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {(r["date"], r["market"]) for r in csv.DictReader(f)}


def record(market: str, row: dict) -> bool:
    """Append one day to days.csv. A day is never written twice."""
    if (row["date"], market) in recorded():
        return False
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "days.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({"market": market, **row})
    return True


def summary() -> None:
    path = os.path.join(OUT_DIR, "days.csv")
    if not os.path.exists(path):
        print("simulation 7 marchés: aucun jour enregistré pour l'instant")
        return
    d = pd.read_csv(path)
    # a market closed on a day (holiday, weekend) earned 0% that day
    daily = d.pivot_table(index="date", columns="market", values="pnl_%")
    eq = (1 + daily.reindex(columns=list(MARKETS)).fillna(0.0) / 100).cumprod()
    total = (eq.iloc[-1].mean() - 1) * 100
    print(
        f"simulation 7 marchés: {d['date'].nunique()} jours, résultat {total:+.2f}% "
        f"({CAPITAL:.0f} -> {CAPITAL * (1 + total / 100):.2f})"
    )


def run_today() -> None:
    """Record every closed day not recorded yet, market by market. A market
    whose prices cannot be fetched or look broken is skipped for this run and
    tried again at the next one; if none can be read the run fails."""
    read = 0
    for name, (ticker, _csv) in MARKETS.items():
        try:
            df = bot.fetch_yahoo(ticker)  # closed candles only
            bot.check_history(name, df)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            RuntimeError,
        ) as e:
            # network error, unexpected reply or failed data check: retry later
            print(f"{name}: skipped ({type(e).__name__}: {e})")
            continue
        read += 1
        for row in day_rows(df, FIRST_DAY):
            if record(name, row):
                print(
                    f"{row['date']} {name}: position {row['position_%']:.0f}%, "
                    f"{row['pnl_%']:+.2f}%"
                )
    summary()
    if not read:
        sys.exit("no market could be read: nothing recorded")


def replay_csv() -> None:
    """Replay the last 60 days of the local CSVs through the same code."""
    global OUT_DIR
    OUT_DIR = os.path.join(HERE, "replay_universe")
    if os.path.exists(os.path.join(OUT_DIR, "days.csv")):
        os.remove(os.path.join(OUT_DIR, "days.csv"))
    for name, (_ticker, f) in MARKETS.items():
        df = bt.load(os.path.join(HERE, "data", f))
        first = df.index.normalize()[-60]
        for row in day_rows(df, first):
            record(name, row)
    summary()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true", help="replay local daily CSVs")
    if ap.parse_args().csv:
        replay_csv()
    else:
        run_today()
