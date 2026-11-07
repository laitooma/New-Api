"""Equal-weight portfolio across markets, each sleeve optionally trend-filtered.
Daily returns of each sleeve are combined on a common calendar (markets that are
closed on a given day contribute 0%). Weights are reset daily (approximation;
the extra rebalancing cost is small at 4 sleeves but not modelled)."""
import numpy as np, pandas as pd
import backtest as bt, strategies as st

MARKETS = {"BTC_USD": 365, "ETH_USD": 365, "XAU_USD": 252, "NAS100_USD": 252}

def sleeve_returns(builder, cost):
    out = {}
    for m, per in MARKETS.items():
        df = bt.load(f"data/{m}_D.csv")
        sig = builder(df, per)
        out[m] = bt.run(df, sig, cost).pct_change()
    r = pd.DataFrame(out)
    r.index = r.index.normalize()
    r = r.groupby(level=0).sum(min_count=1)
    return r.loc["2025-06-26":].fillna(0.0)

def report(name, r, weights=None):
    w = np.ones(r.shape[1]) / r.shape[1] if weights is None else np.array(weights)
    pr = (r * w).sum(axis=1)
    eq = (1 + pr).cumprod()
    cut = eq.index[int(len(eq) * 0.6)]
    m = bt.metrics(eq, pd.Series(1.0, index=eq.index), 365)
    v = eq[cut:]; d = eq[:cut]
    print(f"{name:34s} total {m['total_%']:6.1f}%  annual {m['annual_%']:6.1f}%  maxDD {m['max_dd_%']:6.1f}%  "
          f"sharpe {m['sharpe']:5.2f}  pos.months {m['pos_months_%']:.0f}%  | dev {100*(d.iloc[-1]/d.iloc[0]-1):6.1f}%  val {100*(v.iloc[-1]/v.iloc[0]-1):6.1f}%")
    return eq

if __name__ == "__main__":
    C = 0.002
    bh = sleeve_returns(lambda df, p: st.buy_and_hold(df), C)
    sma = sleeve_returns(lambda df, p: st.sma_trend(df, 50), C)
    vt = sleeve_returns(lambda df, p: st.vol_target(df, st.sma_trend(df, 50), 0.40 if p == 365 else 0.15, 20, p), C)
    report("4 markets buy&hold", bh)
    report("4 markets SMA50 filter", sma)
    report("4 markets SMA50 + vol target", vt)
    report("gold+nasdaq buy&hold 50/50", bh[["XAU_USD","NAS100_USD"]])
    report("crypto SMA50 + gold/nas B&H", pd.concat([sma[["BTC_USD","ETH_USD"]], bh[["XAU_USD","NAS100_USD"]]], axis=1))
