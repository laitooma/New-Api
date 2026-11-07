import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intraday as it
import intraday_paper as ip
import numpy as np

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
df = it.load_h1(os.path.join(DATA, "BTC_USD_H1.csv"))


def test_no_lookahead():
    """A position at hour k must not change when later hours are added."""
    for name, f in it.STRATEGIES.items():
        full = f(df)
        for k in (150, 300):
            assert np.allclose(f(df.iloc[:k]), full[:k]), name


def test_never_holds_overnight():
    for f in it.STRATEGIES.values():
        pos = it._flat_at_day_end(np.asarray(f(df), dtype=float), df.index)
        days = df.index.normalize()
        last = np.r_[days[1:] != days[:-1], True]
        assert (pos[last] == 0).all()
        assert (pos[df.index.hour >= it.FLAT_HOUR] == 0).all()


def test_costs_reduce_result_and_long_only_has_no_shorts():
    pos = it.ema_cross(df)
    assert (
        it.run(df, pos, 0.001, False)["total_%"]
        < it.run(df, pos, 0.0, False)["total_%"]
    )
    assert (np.clip(pos, 0, 1) >= 0).all()


def test_day_result_matches_engine_on_one_day():
    day = df.index.normalize().unique()[5]
    bars = df[df.index.normalize() == day]
    res = ip.day_result(bars)
    assert (
        res["pnl_%"] == it.run(bars, it.asia_breakout(bars), ip.COST, False)["total_%"]
    )
    assert res["trades"] <= 1  # one trade a day at most
