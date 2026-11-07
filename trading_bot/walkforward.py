"""Walk-forward validation: the test any strategy change must pass.

For each step: choose the best variant on the TRAIN window (past only), then
measure it on the next TEST window (never seen when choosing), then move on.
The current strategy (the baseline) is measured on the same test windows.

A change may be proposed only if, after costs, it beats the baseline on at
least PROMOTE_WIN_SHARE of the test windows AND in total, and does so for at
least ROBUST_SHARE of the (train, test) window sizes in WINDOW_GRID. On
2026-11-07 the answer flipped with the window sizes for "best single SMA"
(promoted in 4 of 16 settings), which is exactly what this guards against.

    python walkforward.py             # example: "best single SMA" vs ensemble
"""

import backtest as bt
import numpy as np
import pandas as pd
import strategies as st

MARKETS = ["BTC_USD", "ETH_USD", "XAU_USD"]  # the sleeves the bot trades
COST = 0.002
TRAIN_DAYS, TEST_DAYS, WARMUP_DAYS = 180, 30, 120
PROMOTE_WIN_SHARE = 0.6
ROBUST_SHARE = 0.75
WINDOW_GRID = [(tr, te) for tr in (90, 120, 180, 240) for te in (20, 30, 45, 60)]


def portfolio_returns(builder) -> pd.Series:
    """Daily returns of an equal-weight portfolio of the bot's sleeves, each
    traded with `builder(df) -> target position`. Signals are causal, so
    slicing these returns by date never uses future data."""
    out = {}
    for m in MARKETS:
        df = bt.load(f"data/{m}_D.csv")
        r = bt.run(df, builder(df), COST).pct_change()
        r.index = r.index.normalize()
        out[m] = r.groupby(level=0).sum(min_count=1)
    r = pd.DataFrame(out)
    first_common = max(r[c].first_valid_index() for c in r)  # all sleeves have data
    # markets closed on a day (gold at weekends) contribute 0% that day
    return r.loc[first_common:].fillna(0.0).mean(axis=1)


def _total(r: pd.Series) -> float:
    return float((1 + r).prod() - 1)


def walk_forward(
    variants: dict, baseline, train_days: int = 0, test_days: int = 0
) -> pd.DataFrame:
    """variants: {name: builder}. Returns one row per test window."""
    train_days, test_days = train_days or TRAIN_DAYS, test_days or TEST_DAYS
    base = portfolio_returns(baseline)
    var = {n: portfolio_returns(b) for n, b in variants.items()}
    days = base.index
    rows = []
    start = days[0] + pd.Timedelta(days=WARMUP_DAYS + train_days)
    while start + pd.Timedelta(days=test_days) <= days[-1]:
        train = (days >= start - pd.Timedelta(days=train_days)) & (days < start)
        test = (days >= start) & (days < start + pd.Timedelta(days=test_days))
        best = max(var, key=lambda n: _total(var[n][train]))
        rows.append(
            {
                "test_start": start.date(),
                "chosen": best,
                "candidate_%": round(_total(var[best][test]) * 100, 2),
                "baseline_%": round(_total(base[test]) * 100, 2),
            }
        )
        start += pd.Timedelta(days=test_days)
    return pd.DataFrame(rows)


def verdict(wf: pd.DataFrame) -> dict:
    cand = float(np.prod(1 + wf["candidate_%"] / 100) - 1)
    base = float(np.prod(1 + wf["baseline_%"] / 100) - 1)
    share = float((wf["candidate_%"] > wf["baseline_%"]).mean())
    return {
        "windows": len(wf),
        "candidate_total_%": round(cand * 100, 2),
        "baseline_total_%": round(base * 100, 2),
        "windows_won_%": round(share * 100),
        "promote": bool(share >= PROMOTE_WIN_SHARE and cand > base),
    }


def robust_verdict(variants: dict, baseline) -> dict:
    """Run the walk-forward for every window size in WINDOW_GRID."""
    runs = [verdict(walk_forward(variants, baseline, tr, te)) for tr, te in WINDOW_GRID]
    share = sum(r["promote"] for r in runs) / len(runs)
    return {
        "settings": len(runs),
        "settings_promoting_%": round(share * 100),
        "promote": share >= ROBUST_SHARE,
    }


if __name__ == "__main__":
    # Example question: would picking the best single SMA length on the last
    # 180 days beat the current 7-length ensemble?
    grid = {
        f"sma{n}": (lambda df, n=n: st.sma_trend(df, n)) for n in range(20, 160, 10)
    }
    wf = walk_forward(grid, st.sma_ensemble)
    pd.set_option("display.width", 160)
    print(wf.to_string(index=False))
    print(verdict(wf))
    print(robust_verdict(grid, st.sma_ensemble))
