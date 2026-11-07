"""Run every day-trading strategy on every hourly market, with and without costs.
Costs are per side: crypto on a low-fee spot exchange 0.10%, gold 0.03% and
EUR/USD 0.01% at a low-spread broker (optimistic for a 500 EUR account)."""

import intraday as it
import pandas as pd

MARKETS = {"BTC_USD": 0.001, "ETH_USD": 0.001, "XAU_USD": 0.0003, "EUR_USD": 0.0001}

rows = []
for m, cost in MARKETS.items():
    df = it.load_h1(f"data/{m}_H1.csv")
    bh = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    for name, f in it.STRATEGIES.items():
        pos = f(df)
        for lo in (True, False):
            gross = it.run(df, pos, 0.0, lo)
            net = it.run(df, pos, cost, lo)
            rows.append(
                {
                    "marché": m,
                    "stratégie": name,
                    "sens": "achat" if lo else "achat+vente",
                    "brut_%": gross["total_%"],
                    "net_%": net["total_%"],
                    "frais_%": net["frais_payés_%"],
                    "trades": net["trades"],
                    "jours+_%": net["jours_gagnants_%"],
                    "pire_baisse_%": net["max_dd_%"],
                    "garder_%": round(bh, 2),
                }
            )
out = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(f"période: ~{len(df) // 24} jours de bougies 1h\n")
print(out.to_string(index=False))
print(
    f"\ncombinaisons nettes positives: {(out['net_%'] > 0).sum()} / {len(out)}"
    f"   brutes positives: {(out['brut_%'] > 0).sum()} / {len(out)}"
)
print(f"moyenne nette par combinaison: {out['net_%'].mean():.2f}%")
