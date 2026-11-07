"""Daily trend-following bot: 4 markets, equal weight, SMA-ensemble filter.

Run once a day, just after 00:00 UTC (the daily candle close):
    python bot.py                 # paper trading (default, no money involved)
    python bot.py --live          # real orders on the exchange (needs API keys)
    python bot.py --replay        # replay the bot over local history (check)

Safety:
- paper mode unless --live AND API keys are set;
- kill switch: if equity falls KILL_SWITCH_DD below its peak, sell everything
  and refuse to trade until state.json is edited by hand;
- only closed daily candles are used (today's unfinished candle is dropped);
- rebalances only when a sleeve is off target by more than REBALANCE_BAND.
"""

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime

import pandas as pd
from strategies import sma_ensemble

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.getenv("BOT_STATE_DIR", HERE)
STATE = os.path.join(STATE_DIR, "state.json")
LOG = os.path.join(STATE_DIR, "trades.csv")
EQUITY_LOG = os.path.join(STATE_DIR, "equity.csv")

CAPITAL = 500.0  # starting capital (quote currency, e.g. EUR/USDC)
QUOTE = os.getenv("BOT_QUOTE", "USDC")
FEE = 0.001  # exchange fee per side used in paper mode (Binance spot)
SLIPPAGE = 0.001  # extra cost assumed in paper mode
REBALANCE_BAND = 0.05  # trade a sleeve only if off target by > 5% of equity
KILL_SWITCH_DD = 0.20  # stop everything after a 20% fall from peak
MAX_BUY_FRACTION = 0.40  # a buy above 40% of equity can only be a bug or a bad price
MIN_HISTORY = 101  # longest SMA (100) + 1

# kind "exchange": traded automatically. kind "manual": the bot tells you
# what to hold, you place the order at your broker (e.g. a Nasdaq-100 ETF).
SLEEVES = {
    "BTC": {"kind": "exchange", "symbol": f"BTC/{QUOTE}", "csv": "BTC_USD_D.csv"},
    "ETH": {"kind": "exchange", "symbol": f"ETH/{QUOTE}", "csv": "ETH_USD_D.csv"},
    "GOLD": {"kind": "exchange", "symbol": f"PAXG/{QUOTE}", "csv": "XAU_USD_D.csv"},
}
# Optional 4th sleeve, traded by hand at a broker. Off by default: it needs ~5
# small manual orders a month, and a 1 EUR broker fee on a 30 EUR order is 3%.
if os.getenv("BOT_WITH_NASDAQ") == "1":
    SLEEVES["NASDAQ"] = {"kind": "manual", "yahoo": "QQQ", "csv": "NAS100_USD_D.csv"}


# ---------------------------------------------------------------- data
def closed_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Drop today's still-forming candle."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    return df[df.index < today]


MAX_DAILY_MOVE = 0.35  # 2x the largest real daily move seen (ETH, 17.5%)
MAX_AGE_DAYS = 4  # last closed candle may be at most this old (weekends)
MAX_GAP_DAYS = 5  # largest hole allowed between two candles


class DataError(RuntimeError):
    """Raised when market data looks wrong: the bot then trades nothing."""


def check_history(name: str, df: pd.DataFrame, today=None) -> None:
    """Refuse to trade on data that looks broken (zero/negative or missing
    prices, high below low, stale feed, holes, or an absurd price jump)."""
    today = today or pd.Timestamp.now(tz="UTC").normalize()
    recent = df.iloc[-(MIN_HISTORY + 1) :]
    cols = recent[["open", "high", "low", "close"]]
    if len(recent) < MIN_HISTORY:
        raise DataError(f"{name}: only {len(recent)} candles, need {MIN_HISTORY}")
    if cols.isna().any().any() or (cols <= 0).any().any():
        raise DataError(f"{name}: missing or non-positive prices")
    if (recent["high"] < recent["low"]).any():
        raise DataError(f"{name}: a candle has high below low")
    age = (today - recent.index[-1].normalize()).days
    if age > MAX_AGE_DAYS:
        raise DataError(f"{name}: last candle is {age} days old (feed stale?)")
    gap = recent.index.to_series().diff().dt.days.max()
    if gap > MAX_GAP_DAYS:
        raise DataError(f"{name}: {gap:.0f}-day hole in the data")
    move = recent["close"].pct_change().abs().max()
    if move > MAX_DAILY_MOVE:
        raise DataError(f"{name}: {move:.0%} one-day move, looks like a bad price")


def fetch_exchange(ex, symbol: str) -> pd.DataFrame:
    rows = ex.fetch_ohlcv(symbol, "1d", limit=200)
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "vol"])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return closed_daily(df[["open", "high", "low", "close"]])


def fetch_yahoo(ticker: str) -> pd.DataFrame:
    import requests

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
    j = requests.get(url, timeout=20, headers={"User-Agent": "trend-bot"}).json()
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q[k] for k in ["open", "high", "low", "close"]},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True).normalize(),
    )
    return closed_daily(df.dropna())


def load_csv(name: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(HERE, "data", name))
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


# ---------------------------------------------------------------- logic
def target_weights(history: dict) -> dict:
    """Weight of total equity each sleeve should hold (sums to <= 1)."""
    w = {}
    for name, df in history.items():
        if len(df) < MIN_HISTORY:
            raise RuntimeError(
                f"{name}: only {len(df)} daily candles, need {MIN_HISTORY}"
            )
        w[name] = sma_ensemble(df).iloc[-1] / len(SLEEVES)
    return w


def new_state() -> dict:
    return {
        "cash": CAPITAL,
        "qty": {k: 0.0 for k in SLEEVES},
        "peak": CAPITAL,
        "halted": False,
        "mode": "paper",
    }


def load_state() -> dict:
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return new_state()


def save_state(s: dict) -> None:
    with open(STATE, "w") as f:
        json.dump(s, f, indent=2)


def log_trade(row: dict) -> None:
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def plan_orders(state: dict, prices: dict, weights: dict) -> tuple:
    """Return (equity, {sleeve: value_to_buy(+)/sell(-)})."""
    equity = state["cash"] + sum(state["qty"][k] * prices[k] for k in SLEEVES)
    orders = {}
    for k in SLEEVES:
        current = state["qty"][k] * prices[k]
        wanted = weights.get(k, 0.0) * equity
        if abs(wanted - current) > REBALANCE_BAND * equity or (
            wanted == 0 and current > 0
        ):
            orders[k] = wanted - current
    return equity, orders


def paper_fill(state: dict, k: str, value: float, price: float, when: str) -> None:
    cost = FEE + SLIPPAGE
    if value > 0:
        value = min(value, state["cash"] / (1 + cost))
        state["cash"] -= value * (1 + cost)
        state["qty"][k] += value / price
    else:
        qty = min(-value / price, state["qty"][k])
        state["qty"][k] -= qty
        state["cash"] += qty * price * (1 - cost)
        value = -qty * price
    log_trade(
        {
            "time": when,
            "mode": "paper",
            "sleeve": k,
            "side": "buy" if value > 0 else "sell",
            "value": round(value, 2),
            "price": price,
        }
    )


def live_fill(ex, k: str, value: float, price: float, when: str) -> None:
    sym = SLEEVES[k]["symbol"]
    m = ex.market(sym)
    amount = float(ex.amount_to_precision(sym, abs(value) / price))
    min_cost = (m.get("limits", {}).get("cost", {}) or {}).get("min") or 0
    if amount <= 0 or abs(value) < min_cost:
        print(f"  {k}: order {value:.2f} below exchange minimum, skipped")
        return
    side = "buy" if value > 0 else "sell"
    o = ex.create_order(sym, "market", side, amount)
    log_trade(
        {
            "time": when,
            "mode": "live",
            "sleeve": k,
            "side": side,
            "value": round(value, 2),
            "price": price,
            "order_id": o.get("id"),
        }
    )
    print(f"  {k}: {side} {amount} {sym} (~{abs(value):.2f} {QUOTE})")


def sync_live_state(ex, state: dict) -> None:
    bal = ex.fetch_balance()["total"]
    state["cash"] = float(bal.get(QUOTE, 0.0))
    for k, s in SLEEVES.items():
        if s["kind"] == "exchange":
            state["qty"][k] = float(bal.get(s["symbol"].split("/")[0], 0.0))


# ---------------------------------------------------------------- one daily step
def step(
    state: dict, history: dict, exec_prices: dict, when: str, ex=None, approve=None
) -> dict:
    """Decide on closed candles, trade at exec_prices. Returns a summary.

    `approve(orders, prices) -> bool` is asked before any live order; when it
    says no, nothing is traded. Buys larger than MAX_BUY_FRACTION of equity are
    always blocked (sells never are, so the kill switch can always sell)."""
    equity, _ = plan_orders(state, exec_prices, {})
    state["peak"] = max(state["peak"], equity)
    dd = 1 - equity / state["peak"]

    if state["halted"]:
        return {
            "equity": equity,
            "note": "HALTED (kill switch) - edit state.json to resume",
        }

    if dd >= KILL_SWITCH_DD:
        weights = {k: 0.0 for k in SLEEVES}
        state["halted"] = True
        note = f"KILL SWITCH: drawdown {dd:.0%} >= {KILL_SWITCH_DD:.0%}, selling everything"
    else:
        weights = target_weights(history)
        note = ""
    report = dict(weights)
    if ex is not None:
        # live: only exchange sleeves live on the exchange account, so each gets
        # an equal share of THAT account; the manual sleeve is held elsewhere.
        n_ex = sum(1 for s in SLEEVES.values() if s["kind"] == "exchange")
        weights = {
            k: (w * len(SLEEVES) / n_ex if SLEEVES[k]["kind"] == "exchange" else 0.0)
            for k, w in weights.items()
        }

    equity, orders = plan_orders(state, exec_prices, weights)
    blocked = {k: v for k, v in orders.items() if v > MAX_BUY_FRACTION * equity}
    for k, v in blocked.items():
        del orders[k]
        note += f" BLOCKED: buy of {v:.2f} in {k} is above {MAX_BUY_FRACTION:.0%} of equity."
    if (
        ex is not None
        and approve is not None
        and orders
        and not approve(orders, exec_prices)
    ):
        return {
            "equity": equity,
            "drawdown": dd,
            "weights": report,
            "orders": {},
            "note": (note + " Orders NOT approved: nothing traded.").strip(),
        }
    # sells first so cash is available for buys
    for k, v in sorted(orders.items(), key=lambda kv: kv[1]):
        if ex is not None and SLEEVES[k]["kind"] == "exchange":
            if v < 0:  # never sell more than we hold
                v = -min(-v, state["qty"][k] * exec_prices[k])
            live_fill(ex, k, v, exec_prices[k], when)
        elif ex is None:
            paper_fill(state, k, v, exec_prices[k], when)
    return {
        "equity": equity,
        "drawdown": dd,
        "weights": report,
        "orders": orders,
        "note": note.strip(),
    }


# ---------------------------------------------------------------- modes
def ask_approval(orders: dict, prices: dict) -> bool:
    """Show the planned real orders and wait for the user to type OUI.
    Without a terminal (cron, CI) the answer is no."""
    print("Ordres REELS prevus :")
    for k, v in orders.items():
        print(
            f"  {'ACHAT' if v > 0 else 'VENTE'} {k}: {abs(v):.2f} {QUOTE} au prix ~{prices[k]}"
        )
    try:
        return input("Tape OUI pour passer ces ordres : ").strip() == "OUI"
    except EOFError:
        print("pas de terminal : ordres refuses")
        return False


def run_today(live: bool, yes: bool = False) -> None:
    import ccxt

    exchange_id = os.getenv("BOT_EXCHANGE", "binance")
    key, secret = os.getenv("BOT_API_KEY"), os.getenv("BOT_API_SECRET")
    if live and not (key and secret):
        sys.exit("--live needs BOT_API_KEY and BOT_API_SECRET set. Nothing done.")
    ex = getattr(ccxt, exchange_id)(
        {"apiKey": key, "secret": secret, "enableRateLimit": True}
    )
    ex.load_markets()
    for k, s in SLEEVES.items():
        if s["kind"] == "exchange" and s["symbol"] not in ex.markets:
            sys.exit(
                f"{s['symbol']} not listed on {exchange_id}. Set BOT_QUOTE or edit SLEEVES."
            )

    history, prices = {}, {}
    for k, s in SLEEVES.items():
        if s["kind"] == "exchange":
            history[k] = fetch_exchange(ex, s["symbol"])
            prices[k] = float(ex.fetch_ticker(s["symbol"])["last"])
        else:
            history[k] = fetch_yahoo(s["yahoo"])
            prices[k] = float(history[k]["close"].iloc[-1])

    try:
        for k, h in history.items():
            check_history(k, h)
    except DataError as e:
        sys.exit(f"DATA CHECK FAILED, nothing traded: {e}")

    state = load_state()
    today = str(datetime.now(UTC).date())
    if state.get("last_run") == today:
        print(f"already ran for {today}, nothing done")
        return
    if live:
        state["mode"] = "live"
        sync_live_state(ex, state)
    when = datetime.now(UTC).isoformat(timespec="seconds")
    approve = None if (yes or not live) else ask_approval
    out = step(state, history, prices, when, ex if live else None, approve)
    state["last_run"] = today
    save_state(state)
    log_equity(today, state, prices, out)

    print(
        f"{when}  mode={'LIVE' if live else 'paper'}  equity={out['equity']:.2f} {QUOTE}"
    )
    if out.get("note"):
        print("  " + out["note"])
    for k, w in out.get("weights", {}).items():
        line = f"  {k:7s} target {w * 100:5.1f}% of equity"
        if SLEEVES[k]["kind"] == "manual":
            line += f"  -> MANUAL: hold {w * len(SLEEVES) * 100:.0f}% of your Nasdaq sleeve in a Nasdaq-100 ETF"
        print(line)


def log_equity(day, state: dict, prices: dict, out: dict) -> float:
    equity = state["cash"] + sum(state["qty"][k] * prices[k] for k in SLEEVES)
    new = not os.path.exists(EQUITY_LOG)
    with open(EQUITY_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "equity"] + [f"w_{k}" for k in SLEEVES])
        weights = out.get("weights", {})
        w.writerow(
            [day, round(equity, 2)] + [round(weights.get(k, 0), 3) for k in SLEEVES]
        )
    return equity


def run_paper_csv() -> None:
    """Paper trading from the local CSVs in data/ (kept up to date by
    update_data.py). Decides on yesterday's closed candle and fills at
    today's open, like the backtest. Runs at most once per UTC day."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    data = {k: load_csv(s["csv"]) for k, s in SLEEVES.items()}
    hist = {k: closed_daily(d) for k, d in data.items()}
    try:
        for k, h in hist.items():
            check_history(k, h, today)
    except DataError as e:
        sys.exit(f"DATA CHECK FAILED, nothing traded: {e} (run update_data.py?)")
    prices = {}
    for k, d in data.items():
        row = d[d.index.normalize() == today]
        prices[k] = (
            float(row["open"].iloc[0]) if len(row) else float(hist[k]["close"].iloc[-1])
        )
    state = load_state()
    if state.get("last_run") == str(today.date()):
        print(f"already ran for {today.date()}, nothing done")
        return
    out = step(state, hist, prices, today.isoformat())
    state["last_run"] = str(today.date())
    save_state(state)
    equity = log_equity(today.date(), state, prices, out)
    print(
        f"{today.date()} paper equity {equity:.2f} ({(equity / CAPITAL - 1) * 100:+.2f}% since start)"
    )
    if out.get("note"):
        print("  " + out["note"])
    for k in SLEEVES:
        print(
            f"  {k:5s} target {out.get('weights', {}).get(k, 0) * 100:5.1f}%  held {state['qty'][k] * prices[k]:7.2f}"
        )
    for k, v in out.get("orders", {}).items():
        print(f"  order {k}: {'buy' if v > 0 else 'sell'} {abs(v):.2f}")


def replay(cost_check: bool = True) -> pd.Series:
    """Run the exact bot logic day by day over the local CSV history,
    deciding on closed candles up to day t and filling at day t+1's open."""
    global STATE, LOG
    STATE = os.path.join(HERE, "replay_state.json")
    LOG = os.path.join(HERE, "replay_trades.csv")
    for p in (STATE, LOG):
        if os.path.exists(p):
            os.remove(p)
    data = {k: load_csv(s["csv"]) for k, s in SLEEVES.items()}
    days = sorted(set().union(*[d.index.normalize() for d in data.values()]))
    days = [d for d in days if d >= pd.Timestamp("2025-06-26", tz="UTC")]
    state = new_state()
    curve = {}
    for i in range(len(days) - 1):
        today, nxt = days[i], days[i + 1]
        hist = {k: d[d.index.normalize() <= today] for k, d in data.items()}
        if any(len(h) < MIN_HISTORY for h in hist.values()):
            continue
        # fill at next day's open where the market trades, else last close
        px = {}
        for k, d in data.items():
            row = d[d.index.normalize() == nxt]
            px[k] = (
                float(row["open"].iloc[0])
                if len(row)
                else float(hist[k]["close"].iloc[-1])
            )
        out = step(state, hist, px, nxt.isoformat())
        curve[nxt] = out["equity"]
    eq = pd.Series(curve)
    mark = {k: float(d["close"].iloc[-1]) for k, d in data.items()}
    final = state["cash"] + sum(state["qty"][k] * mark[k] for k in SLEEVES)
    peak = eq.cummax()
    print(
        f"replay {eq.index[0].date()} -> {eq.index[-1].date()}: start {CAPITAL:.0f}, "
        f"end {final:.2f} ({(final / CAPITAL - 1) * 100:+.1f}%), max drawdown {((eq / peak) - 1).min() * 100:.1f}%, "
        f"halted={state['halted']}"
    )
    return eq


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="place real orders")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="with --live: do not ask before each real order (unattended use only)",
    )
    ap.add_argument("--replay", action="store_true", help="replay over local history")
    ap.add_argument(
        "--paper-csv", action="store_true", help="paper trade from data/*.csv"
    )
    a = ap.parse_args()
    if a.replay:
        replay()
    elif a.paper_csv:
        run_paper_csv()
    else:
        run_today(a.live, a.yes)
