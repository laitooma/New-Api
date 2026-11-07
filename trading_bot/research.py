"""Run every strategy on every market, full period and split in two halves
(first 60% = development, last 40% = validation never used to choose)."""
import pandas as pd
import backtest as bt
import strategies as st

MARKETS = {"BTC_USD": 365, "ETH_USD": 365, "XAU_USD": 252, "NAS100_USD": 252}
COST = 0.002  # 0.1% fee + 0.1% slippage per side (low-cost exchange)

def strats(df, per):
    return {
        "buy_hold": st.buy_and_hold(df),
        "sma20": st.sma_trend(df, 20),
        "sma50": st.sma_trend(df, 50),
        "sma100": st.sma_trend(df, 100),
        "ema20/100": st.ema_cross(df, 20, 100),
        "donchian20/10": st.donchian(df, 20, 10),
        "rsi2_revert": st.rsi_reversion(df),
        "sma50+voltgt": st.vol_target(df, st.sma_trend(df, 50), 0.40 if per == 365 else 0.15, 20, per),
    }

def main(cost=COST):
    rows = []
    for m, per in MARKETS.items():
        df = bt.load(f"data/{m}_D.csv")
        cut = df.index[int(len(df) * 0.6)]
        for name, sig in strats(df, per).items():
            eq = bt.run(df, sig, cost)
            full = bt.metrics(eq, sig, per)
            dev = bt.metrics(eq[:cut], sig, per)
            val = bt.metrics(eq[cut:], sig, per)
            rows.append({"market": m, "strategy": name, **full,
                         "dev_total_%": dev["total_%"], "val_total_%": val["total_%"],
                         "val_dd_%": val["max_dd_%"]})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(f"cost per side = {cost*100:.2f}%   split date ~ {cut.date()}")
    print(out.to_string(index=False))
    return out

if __name__ == "__main__":
    import sys
    main(float(sys.argv[1]) if len(sys.argv) > 1 else COST)
