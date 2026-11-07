import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import backtest as bt
import numpy as np
import pandas as pd
import strategies as st

CRYPTO = {"BTC_USD", "ETH_USD"}
ALL = [
    "BTC_USD",
    "ETH_USD",
    "XAU_USD",
    "NAS100_USD",
    "SPX500_USD",
    "DE30_EUR",
    "WTICO_USD",
    "XAG_USD",
    "EUR_USD",
    "USD_JPY",
]


def sleeves(markets, builder, cost):
    out = {}
    for m in markets:
        df = bt.load(f"data/{m}_D.csv")
        r = bt.run(df, builder(df), cost).pct_change()
        r.index = r.index.normalize()
        out[m] = r.groupby(level=0).sum(min_count=1)
    return pd.DataFrame(out).loc["2025-06-26":].fillna(0.0)


def rep(name, r):
    eq = (1 + r.mean(axis=1)).cumprod()
    cut = eq.index[int(len(eq) * 0.6)]
    d, v = eq[:cut], eq[cut:]
    dd = (eq / eq.cummax() - 1).min()
    pr = r.mean(axis=1)
    sh = pr.mean() / pr.std() * np.sqrt(365)
    mon = eq.resample("ME").last().pct_change().dropna()
    print(
        f"{name:42s} total {100 * (eq.iloc[-1] - 1):6.1f}%  maxDD {100 * dd:6.1f}%  sharpe {sh:5.2f}  mois+ {100 * (mon > 0).mean():3.0f}%  | dev {100 * (d.iloc[-1] / d.iloc[0] - 1):6.1f}%  val {100 * (v.iloc[-1] / v.iloc[0] - 1):6.1f}%"
    )


C = 0.002
ens = sleeves(ALL, lambda d: st.sma_ensemble(d), C)
bh = sleeves(ALL, lambda d: st.buy_and_hold(d), C)
print("--- par marché (ensemble, total %) ---")
for m in ALL:
    e = (1 + ens[m]).prod() - 1
    b = (1 + bh[m]).prod() - 1
    print(f"  {m:11s} bot {100 * e:6.1f}%   acheter&garder {100 * b:6.1f}%")
print("--- portefeuilles ---")
rep("ACTUEL: BTC+ETH+or (ensemble)", ens[["BTC_USD", "ETH_USD", "XAU_USD"]])
rep("10 marchés (ensemble)", ens)
rep("10 marchés acheter&garder", bh)
rep(
    "7 marchés sans crypto ni NAS (ensemble)",
    ens[[m for m in ALL if m not in CRYPTO | {"NAS100_USD"}]],
)
for c in (0.001, 0.005):
    rep(
        f"10 marchés ensemble, frais {c * 100:.1f}%",
        sleeves(ALL, lambda d: st.sma_ensemble(d), c),
    )
print(
    "corrélation moyenne des rendements journaliers:",
    round(bh.corr().values[np.triu_indices(len(ALL), 1)].mean(), 2),
)
