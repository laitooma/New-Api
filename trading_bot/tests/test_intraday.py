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


def test_asia_trade_closed_at_20h():
    """Positions are held at most during the 08:00..19:00 bars: out at 20:00 UTC."""
    import pandas as pd

    pos = it._flat_at_day_end(it.asia_breakout(df), df.index)
    held = pd.Series(np.r_[0.0, pos[:-1]], index=df.index)
    hours = set(held[held != 0].index.hour)
    assert hours and min(hours) >= 8 and max(hours) <= 19


def test_only_unseen_days_are_recorded():
    import pandas as pd

    assert not ip.is_out_of_sample(pd.Timestamp("2026-11-07 22:00", tz="UTC"))
    assert ip.is_out_of_sample(pd.Timestamp("2026-11-08 21:11", tz="UTC"))


def test_missed_days_are_caught_up_once():
    import pandas as pd

    ts = pd.Timestamp
    assert ip.finished_days(ts("2026-11-08 20:59", tz="UTC")) == []  # day 8 not over
    assert [d.day for d in ip.finished_days(ts("2026-11-08 21:30", tz="UTC"))] == [8]
    # runs on the 9th and 10th were skipped: the run on the 11th catches up 8..10
    days = ip.finished_days(ts("2026-11-11 03:00", tz="UTC"))
    assert [d.day for d in days] == [8, 9, 10]


def test_record_never_writes_a_day_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "OUT_DIR", str(tmp_path))
    for _ in range(2):
        ip.record("2026-11-08", "BTC", {"trades": 1, "pnl_%": 0.5})
    assert len((tmp_path / "days.csv").read_text().strip().splitlines()) == 2
    assert ("2026-11-08", "BTC") in ip.recorded()


def test_summary_keeps_a_market_missing_on_the_last_day(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ip, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr(ip, "MARKETS", {"BTC": "", "ETH": ""})
    ip.record("2026-11-08", "BTC", {"trades": 1, "pnl_%": 10.0})
    ip.record("2026-11-08", "ETH", {"trades": 1, "pnl_%": -50.0})
    ip.record("2026-11-09", "BTC", {"trades": 1, "pnl_%": 0.0})
    ip.summary()
    assert "-20.00%" in capsys.readouterr().out  # (1.10 + 0.50) / 2 - 1


def test_bad_hourly_bars_are_refused():
    day = df[df.index.normalize() == df.index.normalize()[-30]]
    assert ip.bars_problem(day) == ""
    # every real day of the local history passes: the check never hides a real day
    for _, g in df.groupby(df.index.normalize()):
        assert ip.bars_problem(g) == ""
    zero = day.copy()
    zero.iloc[5, zero.columns.get_loc("close")] = 0.0
    assert "non-positive" in ip.bars_problem(zero)
    nan = day.copy()
    nan.iloc[5, nan.columns.get_loc("low")] = np.nan
    assert "missing" in ip.bars_problem(nan)
    inverted = day.copy()
    inverted.iloc[5, inverted.columns.get_loc("high")] = inverted["low"].iloc[5] / 2
    assert "high below low" in ip.bars_problem(inverted)
    spike = day.copy()
    spike.iloc[5, spike.columns.get_loc("close")] *= 2
    assert "one-hour move" in ip.bars_problem(spike)


def test_day_trade_matches_the_recorded_result():
    """Entry/exit of the logged trade must explain the day's result: price
    move in the trade's direction minus 0.10% per side."""
    seen = 0
    for _, bars in df.groupby(df.index.normalize()):
        if len(bars) < 21:
            continue
        res = ip.day_result(bars)
        trade = ip.day_trade(bars, res["pnl_%"])
        assert (trade is None) == (res["trades"] == 0)
        if trade is None:
            continue
        seen += 1
        sign = 1 if trade["side"] == "achat" else -1
        move = sign * (trade["exit_price"] / trade["entry_price"] - 1) * 100
        # the engine compounds hour by hour, so on a large move the result is
        # a few hundredths of a point away from the plain entry/exit figure
        gap = abs(move - 2 * ip.COST * 100 - res["pnl_%"])
        assert gap < 0.03 + 0.03 * abs(move)
        assert trade["exit_time"].endswith("20:00")
        assert "08:00" <= trade["entry_time"][-5:] <= "19:00"
    assert seen > 10


def test_trades_are_logged_and_backfilled_once(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(ip, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr(ip, "MARKETS", {"BTC": "BTC/USD"})
    monkeypatch.setattr(ip, "fetch_kraken", lambda sym: df)
    days = [d for d, g in df.groupby(df.index.normalize()) if len(g) >= 21][-6:]
    traded = [d for d in days if ip.day_result(df[df.index.normalize() == d])["trades"]]
    monkeypatch.setattr(ip, "finished_days", lambda now: days)
    # the oldest traded day was recorded before trades.csv existed
    old = traded[0]
    ip.record(old.date(), "BTC", {"trades": 1, "pnl_%": 9.99})
    for _ in range(2):  # the second run must add nothing
        ip.run_today()
    rows = pd.read_csv(tmp_path / "trades.csv")
    assert len(rows) == len(traded) and not rows.duplicated(["date", "market"]).any()
    # the backfilled trade keeps the result already on record
    assert rows.loc[rows["date"] == str(old.date()), "pnl_%"].iloc[0] == 9.99
    recorded = pd.read_csv(tmp_path / "days.csv")
    assert len(recorded) == len(days) and not recorded.duplicated(["date"]).any()
    assert recorded.loc[recorded["date"] == str(old.date()), "pnl_%"].iloc[0] == 9.99
