import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest as bt
import bot
import numpy as np
import pandas as pd
import strategies as st

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
df = bt.load(os.path.join(DATA, "BTC_USD_D.csv"))


def test_no_lookahead():
    """A signal on day k must not change when future candles are added."""
    full = st.sma_ensemble(df)
    for k in (150, 300, 450):
        part = st.sma_ensemble(df.iloc[:k])
        assert np.allclose(part.values, full.iloc[:k].values)
    for f in (lambda d: st.donchian(d), lambda d: st.rsi_reversion(d)):
        assert np.allclose(f(df.iloc[:300]).values, f(df).iloc[:300].values)


def test_engine_buy_hold_exact():
    eq = bt.run(df, st.buy_and_hold(df), 0.0)
    assert abs(eq.iloc[-1] - df.close.iloc[-1] / df.open.iloc[1]) < 1e-9


def test_engine_charges_costs():
    assert (
        bt.run(df, st.sma_trend(df, 20), 0.01).iloc[-1]
        < bt.run(df, st.sma_trend(df, 20), 0.0).iloc[-1]
    )


def test_ensemble_bounds():
    s = st.sma_ensemble(df)
    assert s.min() >= 0 and s.max() <= 1


def test_kill_switch_sells_everything(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    state = bot.new_state()
    state["cash"] = 0.0
    state["qty"] = {k: 1.0 for k in bot.SLEEVES}
    state["peak"] = 1000.0
    prices = {k: 175.0 for k in bot.SLEEVES}  # equity 700 -> 30% drawdown
    bot.step(state, hist, prices, "t")
    assert state["halted"] is True
    assert all(q == 0 for q in state["qty"].values())
    # once halted it never trades again
    state["cash"] = 0.0
    state["qty"] = {k: 1.0 for k in bot.SLEEVES}
    bot.step(state, hist, prices, "t2")
    assert all(q == 1.0 for q in state["qty"].values())


def test_never_spends_more_than_cash(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    state = bot.new_state()
    bot.step(state, hist, {k: 100.0 for k in bot.SLEEVES}, "t")
    assert state["cash"] >= -1e-9


def test_closed_daily_drops_today():
    today = pd.Timestamp.now(tz="UTC").normalize()
    d = pd.DataFrame({"close": [1, 2]}, index=[today - pd.Timedelta(days=1), today])
    assert len(bot.closed_daily(d)) == 1


class FakeExchange:
    def __init__(self):
        self.orders = []

    def market(self, sym):
        return {"limits": {"cost": {"min": 5}}}

    def amount_to_precision(self, sym, a):
        return f"{a:.6f}"

    def create_order(self, sym, typ, side, amount):
        self.orders.append((sym, side, amount))
        return {"id": str(len(self.orders))}


def test_live_uses_whole_exchange_account(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    w = bot.target_weights(hist)["BTC"] * len(bot.SLEEVES)  # ensemble value
    state = bot.new_state()
    state["cash"] = 375.0
    state["peak"] = 375.0
    ex = FakeExchange()
    bot.step(state, hist, {k: 100.0 for k in bot.SLEEVES}, "t", ex)
    bought = sum(a * 100.0 for _, side, a in ex.orders if side == "buy")
    assert not any(s.startswith("NASDAQ") for s, _, _ in ex.orders)
    assert abs(bought - 375.0 * w) < 1.0  # 3 sleeves x 1/3 x ensemble


def test_live_sell_capped_at_holdings(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    state = bot.new_state()
    state["cash"] = 0.0
    state["peak"] = 10_000.0
    state["qty"] = {"BTC": 1.0, "ETH": 0.0, "GOLD": 0.0, "NASDAQ": 0.0}
    ex = FakeExchange()
    bot.step(
        state, hist, {k: 100.0 for k in bot.SLEEVES}, "t", ex
    )  # kill switch -> sell all
    sold = [a for s, side, a in ex.orders if side == "sell"]
    assert sold and max(sold) <= 1.0 + 1e-9


class FakeCcxtExchange:
    """Stands in for a ccxt exchange in paper mode (no network)."""

    def __init__(self, cfg):
        self.markets = {s["symbol"]: {} for s in bot.SLEEVES.values()}

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, tf, limit):
        d = df.iloc[-limit:]
        return [
            [int(t.timestamp() * 1000), r.open, r.high, r.low, r.close, 0]
            for t, r in d.iterrows()
        ]

    def fetch_ticker(self, symbol):
        return {"last": float(df.close.iloc[-1])}


def test_run_today_paper_runs_once_per_day(tmp_path, monkeypatch):
    import types

    fake = types.SimpleNamespace(binance=FakeCcxtExchange, kraken=FakeCcxtExchange)
    monkeypatch.setitem(sys.modules, "ccxt", fake)
    monkeypatch.setattr(bot, "STATE", str(tmp_path / "s.json"))
    monkeypatch.setattr(bot, "LOG", str(tmp_path / "t.csv"))
    monkeypatch.setattr(bot, "EQUITY_LOG", str(tmp_path / "e.csv"))
    bot.run_today(live=False)
    bot.run_today(live=False)  # second call the same day must do nothing
    lines = (tmp_path / "e.csv").read_text().strip().splitlines()
    assert len(lines) == 2  # header + one day


def _recent():
    """Real BTC history re-dated so its last closed candle is yesterday."""
    d = df.copy()
    shift = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1) - d.index[-1]
    d.index = d.index + shift
    return d


def test_check_history_accepts_real_data():
    for name in ["BTC_USD", "ETH_USD", "XAU_USD", "NAS100_USD"]:
        d = bt.load(os.path.join(DATA, f"{name}_D.csv"))
        bot.check_history(name, d, today=d.index[-1].normalize())


def test_check_history_rejects_bad_data():
    import pytest

    good = _recent()
    bot.check_history("ok", good)
    bad_price = good.copy()
    bad_price.iloc[-1, bad_price.columns.get_loc("close")] *= 3  # +200% spike
    stale = good.copy()
    stale.index = stale.index - pd.Timedelta(days=10)
    zero = good.copy()
    zero.iloc[-5, zero.columns.get_loc("low")] = 0
    holed = good.drop(good.index[-20:-10])
    for broken in (bad_price, stale, zero, holed, good.iloc[-50:]):
        with pytest.raises(bot.DataError):
            bot.check_history("x", broken)


def test_live_orders_need_approval(tmp_path, monkeypatch):
    bot.LOG = str(tmp_path / "t.csv")
    # force a buy signal (the real recent data is in a downtrend: no orders)
    monkeypatch.setattr(bot, "target_weights", lambda h: {k: 0.25 for k in bot.SLEEVES})
    hist = {k: df for k in bot.SLEEVES}
    prices = {k: 100.0 for k in bot.SLEEVES}
    state = bot.new_state()
    state["cash"], state["peak"] = 375.0, 375.0
    ex = FakeExchange()
    out = bot.step(state, hist, prices, "t", ex, approve=lambda o, p: False)
    assert ex.orders == [] and "NOT approved" in out["note"]
    bot.step(state, hist, prices, "t", ex, approve=lambda o, p: True)
    assert ex.orders  # approved -> placed


def test_no_terminal_means_no(monkeypatch):
    def no_tty(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_tty)
    assert bot.ask_approval({"BTC": 10.0}, {"BTC": 1.0}) is False


def test_oversized_buy_is_blocked_but_sells_are_not(tmp_path, monkeypatch):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    prices = {k: 100.0 for k in bot.SLEEVES}
    monkeypatch.setattr(bot, "target_weights", lambda h: {k: 0.9 for k in bot.SLEEVES})
    state = bot.new_state()
    out = bot.step(state, hist, prices, "t")
    assert "BLOCKED" in out["note"] and all(q == 0 for q in state["qty"].values())
    # kill switch: a full sell is never blocked
    state = bot.new_state()
    state["cash"], state["qty"]["BTC"], state["peak"] = 0.0, 10.0, 10_000.0
    bot.step(state, hist, prices, "t")
    assert state["qty"]["BTC"] == 0


def test_refused_kill_switch_sale_is_proposed_again(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    prices = {k: 100.0 for k in bot.SLEEVES}
    state = bot.new_state()
    state["cash"], state["qty"]["BTC"], state["peak"] = 0.0, 1.0, 1000.0
    ex = FakeExchange()
    out = bot.step(state, {}, prices, "t", ex, approve=lambda o, p: False)
    assert "KILL SWITCH" in out["note"] and ex.orders == []
    assert state["halted"] is False  # not stuck: positions are still held
    bot.step(state, {}, prices, "t", ex, approve=lambda o, p: True)
    assert state["halted"] is True and ex.orders  # sold on the next run


def test_paper_fills_at_todays_open_not_at_run_time(tmp_path, monkeypatch):
    import types

    today = pd.Timestamp.now(tz="UTC").normalize()

    class Ex(FakeCcxtExchange):
        def fetch_ohlcv(self, symbol, tf, limit):
            rows = super().fetch_ohlcv(symbol, tf, limit)
            return rows + [[int(today.timestamp() * 1000), 111.0, 130, 100, 125.0, 0]]

        def fetch_ticker(self, symbol):
            return {"last": 125.0}

    seen = {}
    monkeypatch.setitem(sys.modules, "ccxt", types.SimpleNamespace(binance=Ex))
    monkeypatch.delenv("BOT_EXCHANGE", raising=False)
    monkeypatch.setattr(bot, "STATE", str(tmp_path / "s.json"))
    monkeypatch.setattr(bot, "LOG", str(tmp_path / "t.csv"))
    monkeypatch.setattr(bot, "EQUITY_LOG", str(tmp_path / "e.csv"))
    monkeypatch.setattr(bot, "check_history", lambda *a, **k: None)
    monkeypatch.setattr(
        bot, "step", lambda s, h, px, *a, **k: seen.update(px) or {"equity": 500.0}
    )
    bot.run_today(live=False)
    assert set(seen.values()) == {111.0}
