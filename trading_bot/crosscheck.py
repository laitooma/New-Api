"""Independent check: re-run the 0/1 strategies with the open-source
backtesting.py library (github.com/kernc/backtesting.py) and compare with our
own engine. Both fill at the next bar's open and pay a commission per trade."""

import warnings

warnings.filterwarnings("ignore")
import backtest as bt
import pandas as pd
import strategies as st
from backtesting import Backtest, Strategy

COST = 0.002


def make(signal):
    class S(Strategy):
        def init(self):
            self.sig = self.I(lambda: signal.values, name="sig")

        def next(self):
            want = self.sig[-1] > 0.5
            if want and not self.position:
                self.buy(size=0.9999)
            elif not want and self.position:
                self.position.close()

    return S


rows = []
for m in ["BTC_USD", "ETH_USD", "XAU_USD", "NAS100_USD"]:
    df = bt.load(f"data/{m}_D.csv")
    d = df.rename(columns=str.capitalize)
    d.index = d.index.tz_localize(None)
    for name, sig in {
        "sma50": st.sma_trend(df, 50),
        "donchian20/10": st.donchian(df, 20, 10),
    }.items():
        ours = bt.run(df, sig, COST).iloc[-1] - 1
        res = Backtest(
            d,
            make(sig),
            cash=1e9,
            commission=COST,
            trade_on_close=False,
            finalize_trades=True,
        ).run()
        rows.append(
            {
                "market": m,
                "strategy": name,
                "our_engine_%": round(ours * 100, 1),
                "backtesting.py_%": round(res["Return [%]"], 1),
                "trades_bt.py": res["# Trades"],
            }
        )
print(pd.DataFrame(rows).to_string(index=False))
