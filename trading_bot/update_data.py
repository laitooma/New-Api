"""Merge daily candles fetched with the TraderWAI connector (get_ohlc, timeframe D)
into data/<SYMBOL>_D.csv. The connector's replies are read from this Claude
session's transcript (newest .jsonl under ~/.claude/projects), so no number is
ever copied by hand. Newer values overwrite older ones for the same day."""

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
            if (
                o.startswith("OHLC data for ")
                and " D — " in o
                and "Candles (time=unix seconds):" in o
            ):
                sym = o.split()[3]
                found.setdefault(sym, {}).update(
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
    for sym, new in candles_from_transcripts().items():
        path = os.path.join(HERE, "data", f"{sym}_D.csv")
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
        print(f"{sym}: {before} -> {len(rows)} candles, last {max(rows)}")


if __name__ == "__main__":
    main()
