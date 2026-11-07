import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import backtest as bt, strategies as st, bot

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
    assert bt.run(df, st.sma_trend(df, 20), 0.01).iloc[-1] < bt.run(df, st.sma_trend(df, 20), 0.0).iloc[-1]

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
    prices = {k: 175.0 for k in bot.SLEEVES}       # equity 700 -> 30% drawdown
    out = bot.step(state, hist, prices, "t")
    assert state["halted"] is True
    assert all(q == 0 for q in state["qty"].values())
    # once halted it never trades again
    state["cash"] = 0.0; state["qty"] = {k: 1.0 for k in bot.SLEEVES}
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
    def __init__(self): self.orders = []
    def market(self, sym): return {"limits": {"cost": {"min": 5}}}
    def amount_to_precision(self, sym, a): return f"{a:.6f}"
    def create_order(self, sym, typ, side, amount):
        self.orders.append((sym, side, amount)); return {"id": str(len(self.orders))}

def test_live_uses_whole_exchange_account(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    w = bot.target_weights(hist)["BTC"] * len(bot.SLEEVES)   # ensemble value
    state = bot.new_state(); state["cash"] = 375.0; state["peak"] = 375.0
    ex = FakeExchange()
    bot.step(state, hist, {k: 100.0 for k in bot.SLEEVES}, "t", ex)
    bought = sum(a * 100.0 for _, side, a in ex.orders if side == "buy")
    assert not any(s.startswith("NASDAQ") for s, _, _ in ex.orders)
    assert abs(bought - 375.0 * w) < 1.0          # 3 sleeves x 1/3 x ensemble

def test_live_sell_capped_at_holdings(tmp_path):
    bot.LOG = str(tmp_path / "t.csv")
    hist = {k: df for k in bot.SLEEVES}
    state = bot.new_state(); state["cash"] = 0.0; state["peak"] = 10_000.0
    state["qty"] = {"BTC": 1.0, "ETH": 0.0, "GOLD": 0.0, "NASDAQ": 0.0}
    ex = FakeExchange()
    bot.step(state, hist, {k: 100.0 for k in bot.SLEEVES}, "t", ex)   # kill switch -> sell all
    sold = [a for s, side, a in ex.orders if side == "sell"]
    assert sold and max(sold) <= 1.0 + 1e-9
