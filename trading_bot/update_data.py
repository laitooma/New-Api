"""Merge candles fetched with the TraderWAI connector (get_ohlc, any timeframe)
into data/<SYMBOL>_<TF>.csv (e.g. BTC_USD_D.csv, BTC_USD_H1.csv). The connector's replies are read from this Claude
session's transcript (newest .jsonl under ~/.claude/projects), so no number is
ever copied by hand. Newer values overwrite older ones for the same candle."""

import csv
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def candles_from_transcripts():
    files = sorted(
        glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")),
        key=os.path.getmtime,
    )
    found = {}

    def walk(o):
        if isinstance(o, str):
            if o.startswith("OHLC data for ") and "Candles (time=unix seconds):" in o:
                sym, tf = o.split()[3], o.split()[4]
                found.setdefault((sym, tf), {}).update(
                    {
                        c["time"]: c
                        for c in json.loads(
                            o.split("Candles (time=unix seconds):", 1)[1].strip()
                        )
                    }
                )
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in files:  # oldest first, so newest wins
        with open(f) as fh:
            for line in fh:
                try:
                    walk(json.loads(line))
                except json.JSONDecodeError:
                    continue  # partial line (transcript still being written)
    return found


def main():
    for (sym, tf), new in candles_from_transcripts().items():
        path = os.path.join(HERE, "data", f"{sym}_{tf}.csv")
        rows = {}
        if os.path.exists(path):
            with open(path) as fh:
                for r in csv.DictReader(fh):
                    rows[int(r["time"])] = r
        before = len(rows)
        for t, c in new.items():
            rows[int(t)] = {k: c[k] for k in ["time", "open", "high", "low", "close"]}
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["time", "open", "high", "low", "close"],
                lineterminator="\n",
            )
            w.writeheader()
            for t in sorted(rows):
                w.writerow(rows[t])
        print(f"{sym} {tf}: {before} -> {len(rows)} candles, last {max(rows)}")


if __name__ == "__main__":
    main()
