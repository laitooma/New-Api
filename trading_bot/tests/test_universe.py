import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest as bt
import pandas as pd
import strategies as st
import universe_paper as up

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
df = bt.load(os.path.join(DATA, "SPX500_USD_D.csv"))
FIRST = df.index.normalize()[-40]


def test_only_days_from_first_day_are_returned():
    rows = up.day_rows(df, FIRST)
    assert len(rows) == 40 and rows[0]["date"] == str(FIRST.date())
    assert up.day_rows(df, df.index.normalize()[-1] + pd.Timedelta(days=1)) == []


def test_no_lookahead():
    """A recorded day must not change when later candles arrive."""
    full = up.day_rows(df, FIRST)
    for cut in (10, 25):
        part = up.day_rows(df.iloc[:-cut], FIRST)
        assert part == full[: len(part)] and len(part) == 40 - cut


def test_matches_the_backtest_engine_and_starts_flat():
    rows = up.day_rows(df, FIRST)
    target = st.sma_ensemble(df)
    eq = bt.run(df, target, up.COST)
    start = len(df) - 40
    # after the first day the result is the backtest engine's, day for day
    for k in range(1, 40):
        i = start + k
        assert abs(rows[k]["pnl_%"] - (eq.iloc[i] / eq.iloc[i - 1] - 1) * 100) < 1e-3
        assert rows[k]["position_%"] == round(float(target.iloc[i - 1]) * 100, 1)
    # the first day buys the position already signalled and pays for it
    held = float(target.iloc[start - 1])
    intraday = df["close"].iloc[start] / df["open"].iloc[start] - 1
    expected = ((1 - held * up.COST) * (1 + held * intraday) - 1) * 100
    assert abs(rows[0]["pnl_%"] - expected) < 1e-3
    assert rows[0]["position_%"] == round(held * 100, 1)


def test_a_day_is_never_recorded_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "OUT_DIR", str(tmp_path))
    row = {"date": "2026-11-13", "position_%": 100.0, "pnl_%": 0.5}
    assert up.record("SP500", row) is True
    assert up.record("SP500", row) is False
    assert len((tmp_path / "days.csv").read_text().strip().splitlines()) == 2


def test_run_skips_a_broken_market_and_catches_up_once(tmp_path, monkeypatch, capsys):
    import pytest

    monkeypatch.setattr(up, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr(up, "FIRST_DAY", FIRST)
    monkeypatch.setattr(up.bot, "check_history", lambda *a, **k: None)

    def fetch(ticker):
        if ticker == "CL=F":
            raise ConnectionError("no network")
        return df

    monkeypatch.setattr(up.bot, "fetch_yahoo", fetch)
    up.run_today()
    up.run_today()  # second run: nothing new
    rows = pd.read_csv(tmp_path / "days.csv")
    assert len(rows) == 40 * 6 and "PETROLE" not in set(rows["market"])
    assert not rows.duplicated(["date", "market"]).any()
    assert "PETROLE: skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        up.bot, "fetch_yahoo", lambda t: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(SystemExit):
        up.run_today()  # nothing readable at all: the run must fail loudly


def test_summary_is_the_mean_of_seven_equal_sleeves(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(up, "OUT_DIR", str(tmp_path))
    up.record("SP500", {"date": "2026-11-13", "position_%": 100.0, "pnl_%": 7.0})
    up.summary()
    assert "+1.00%" in capsys.readouterr().out  # 7% on one seventh of the capital


def test_still_records_once_first_day_is_older_than_the_price_window():
    """Yahoo returns one year of candles: a year after FIRST_DAY it is no
    longer in the window, and new days must still be recorded, with the
    same result as the backtest engine."""
    window = df.iloc[-260:]
    first = window.index.normalize()[0] - pd.Timedelta(days=30)
    rows = up.day_rows(window, first)
    eq = bt.run(window, st.sma_ensemble(window), up.COST)
    assert rows and rows[-1]["date"] == str(window.index[-1].date())
    for k in (1, 2, 3):
        expected = (eq.iloc[-k] / eq.iloc[-k - 1] - 1) * 100
        assert abs(rows[-k]["pnl_%"] - expected) < 1e-3
