"""
Live record: every saved call in data/signals.csv, scored by what really happened.

Each call is the site's 1-month plan as it stood that day: bought at that day's close,
sold on the first day the high reaches the take-profit (a resting sell order), or on the
first close at or below the stop, or at the close of the last session on or before the
sell-by date. These are the backtest's rules, so live results compare directly with it.

Prices are the bonus / dividend corrected series, so a record-date drop is not mistaken
for a stop. A call is "open" until it hits a level or its sell-by date has passed.
"""

import numpy as np
import pandas as pd

from .expected import COST

PLAN_COLS = ["price", "take_profit", "stop", "sell_by"]
BUCKETS = [0, 0.4, 0.5, 0.6, 0.7, 1.01]


def sell_by_date(date):
    """Bought the next session, held one month (same rule as the site's sell-by)."""
    return (pd.Timestamp(date) + pd.Timedelta(days=1) + pd.DateOffset(months=1)).strftime("%Y-%m-%d")


def fill_plan(sig, m, panel):
    """Add the plan (price, take-profit, stop, sell-by) to rows saved before it was recorded."""
    sig = sig.copy()
    for c in PLAN_COLS:
        if c not in sig:
            sig[c] = np.nan
    sig["sell_by"] = sig["sell_by"].astype(object)
    miss = sig["price"].isna()
    for d, idx in sig[miss].groupby("date").groups.items():
        ts = str(d)
        if ts not in m.dates:
            continue
        syms = sig.loc[idx, "symbol"]
        price = m.raw_close.loc[ts].reindex(syms).values
        pd_ = panel.xs(ts, level="date").reindex(syms)
        sig.loc[idx, "price"] = price
        sig.loc[idx, "take_profit"] = price * (1 + pd_["target_dist"].values)
        sig.loc[idx, "stop"] = price * (1 - pd_["stop_dist"].values)
        sig.loc[idx, "sell_by"] = sell_by_date(d)
    sig[["price", "take_profit", "stop"]] = sig[["price", "take_profit", "stop"]].round(2)
    return sig


def score(sig, m):
    """One row per saved call: status, outcome (take-profit / stop / sell-by), exit date, days held, result."""
    sig = sig.sort_values(["symbol", "date"]).copy()
    prev = sig.groupby("symbol")["verdict"].shift(1)
    sig["first_day"] = sig["verdict"].ne(prev)                  # first session with this tag
    sig = sig.sort_values(["date", "rank"])
    last = m.dates[-1]
    out = []
    for d, g in sig.groupby("date", sort=False):
        ts = str(d)                                  # dates are YYYY-MM-DD text, so text order is date order
        if ts not in m.dates:
            continue
        sb = str(g["sell_by"].iloc[0])
        fut = m.dates[(m.dates > ts) & (m.dates <= sb)]
        syms = g["symbol"].values
        base = m.close.loc[ts].reindex(syms).values
        tgt = (g["take_profit"] / g["price"] - 1).values
        stp = (1 - g["stop"] / g["price"]).values
        hi = m.high.loc[fut].reindex(columns=syms).values / base - 1
        cl = m.close.loc[fut].reindex(columns=syms).values / base - 1
        n = len(fut)
        up, dn = hi >= tgt, cl <= -stp
        iu = np.where(up.any(0), up.argmax(0), n) if n else np.zeros(len(syms), int)
        idn = np.where(dn.any(0), dn.argmax(0), n) if n else np.zeros(len(syms), int)
        done = last >= sb
        res = pd.DataFrame({"date": d, "symbol": syms})
        outcome = np.where((iu < n) & (iu <= idn), "Take-profit", np.where(idn < n, "Stop", np.where(done, "Sell-by", "")))
        res["status"] = np.where(outcome == "", "open", "closed")
        res["outcome"] = outcome
        exit_i = np.where(outcome == "Take-profit", iu, np.where(outcome == "Stop", idn, n - 1))
        now = cl[-1] if n else np.zeros(len(syms))
        res["result"] = np.where(outcome == "Take-profit", tgt, np.where(outcome == "Stop", -stp,
                                 np.where(outcome == "Sell-by", cl[n - 1] if n else 0.0, np.nan)))
        res["net"] = res["result"] - COST
        res["exit_date"] = [str(fut[k]) if (o and n) else "" for k, o in zip(exit_i, outcome)]
        res["days"] = np.where(res["status"] == "closed", exit_i + 1, n)
        res["now"] = np.where(res["status"] == "open", now, np.nan)          # move so far on open calls
        res["to_tp"] = np.where(res["status"] == "open", tgt - now, np.nan)  # still needed to reach the take-profit
        res.loc[np.isnan(base) | np.isnan(tgt) | np.isnan(stp), ["status", "outcome"]] = ["no data", ""]
        out.append(res)
    sc = sig.merge(pd.concat(out), on=["date", "symbol"], how="left")
    keep = ["date", "symbol", "verdict", "rank", "first_day", "phase", "hit", "sell", "price", "take_profit", "stop", "sell_by",
            "status", "outcome", "exit_date", "days", "result", "net", "now", "to_tp"]
    sc = sc[keep]
    for c in ["hit", "sell", "result", "net", "now", "to_tp"]:
        sc[c] = sc[c].round(4)
    return sc.sort_values(["date", "rank"], ascending=[False, True])


def _stats(x):
    return {"n": int(len(x)), "target": float((x["outcome"] == "Take-profit").mean()) if len(x) else None,
            "stop": float((x["outcome"] == "Stop").mean()) if len(x) else None,
            "neither": float((x["outcome"] == "Sell-by").mean()) if len(x) else None,
            "net": float(x["net"].mean()) if len(x) else None, "days": float(x["days"].mean()) if len(x) else None}


def summary(sc, backtest=None, last_date=None):
    """Totals for the site: by tag (every day and first day only), odds check, and the Buy calls one by one.

    Totals use only days whose whole month is over: before that, only the calls that hit a level
    early have finished, which flatters (or punishes) the tally. Until the first such day, the
    early finishes are shown instead, marked as such.
    """
    settled = sc[(sc["sell_by"].astype(str) <= str(last_date)) & (sc["status"] == "closed")]
    basis = "settled" if len(settled) else "early"
    closed = settled if len(settled) else sc[sc["status"] == "closed"]
    by_tag = [{"verdict": v, "all": _stats(closed[closed["verdict"] == v]),
               "first": _stats(closed[(closed["verdict"] == v) & closed["first_day"]]),
               "open": int(((sc["verdict"] == v) & (sc["status"] == "open")).sum())} for v in ["Buy", "Neutral", "Sell"]]
    b = pd.cut(closed["hit"], BUCKETS, right=False)
    odds = [{"bucket": f"{iv.left:.0%}–{min(iv.right, 1):.0%}", "n": int(len(x)), "predicted": float(x["hit"].mean()),
             "actual": float((x["outcome"] == "Take-profit").mean()), "stop": float((x["outcome"] == "Stop").mean())}
            for iv, x in closed.groupby(b, observed=True) if len(x)]
    buys = sc[(sc["verdict"] == "Buy") & sc["first_day"]].head(600)
    rows = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in
            buys[["date", "symbol", "rank", "phase", "hit", "sell", "price", "take_profit", "stop", "sell_by", "status", "outcome",
                  "exit_date", "days", "result", "net", "now", "to_tp"]].to_dict("records")]
    for r in rows:
        r["days"] = None if r["days"] is None else int(r["days"])
    opens = sc[sc["status"] == "open"]
    return {"asof": str(last_date) if last_date is not None else None, "first_signal": str(sc["date"].min()),
            "calls": int(len(sc)), "closed": int(len(closed)), "open": int(len(opens)),
            "next_close": (str(opens["sell_by"].min()) if len(opens) else None), "basis": basis,
            "settled_days": int(settled["date"].nunique()), "finished": int((sc["status"] == "closed").sum()),
            "by_tag": by_tag, "odds": odds, "backtest": backtest or [], "buys": rows}
