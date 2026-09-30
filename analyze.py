"""
Score every DSE share for the next 2 weeks (10 trading days) and build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

For each share:
- expected 2-week move, from calibrated odds of a >3% rise vs a >3% fall
- journey: where it is on its current swing (bottoming, early rise, ... late fall)
- tag: Buy = expected +1% or more while bottoming / late in a fall / early in a rise;
  Sell = expected -0.5% or worse while falling / topping; everything else Neutral
- projected path: expected price in 2 weeks with the share's usual spread around it

Everything is checked walk-forward on periods the model never saw, and today's
scores are appended to data/signals.csv (a forward record the model can never revise).
"""

import argparse
import os
import time
import warnings

import numpy as np
import pandas as pd

from analysis import backtest, expected as E, features, model, prep, report

SITE_DATA = "site/data"
SIGNALS_CSV = "data/signals.csv"
SIGNAL_COLS = ["date", "symbol", "horizon", "buy", "sell", "move", "direction", "exp", "phase", "conf", "verdict", "rank"]
BUCKETS = ([-9, -0.005, 0, 0.01, 9],
           ["−0.5% or worse", "−0.5% to 0%", "0% to +1%", "+1% or more"])


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def build_table(t, panel_day, avg):
    """Day table -> expected move, journey, verdict and ranking."""
    t = t.copy()
    p = panel_day.reindex(t.index)
    t["exp"] = E.outlook(t, avg)
    t["phase"] = E.phase(p["leg_dir"], p["leg_progress"], p["ret5"])
    t["verdict"] = E.journey_verdict(t["exp"], t["phase"])
    t["tier"] = t["verdict"].map(E.TIER)
    # Buys first, then Neutral, each ordered by expected move (sells mirror this).
    t["rank_score"] = t["tier"] + t["exp"].clip(-0.5, 0.5) + 1e-6 * t["conf"]
    t["sell_score"] = (2 - t["tier"]) - t["exp"].clip(-0.5, 0.5) + 1e-6 * t["conf"]
    t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
    return t


def verdict_check(sc, panel, fwd, avg, universe):
    """How each verdict turned out on unseen days (all out-of-sample days, not just rebalances)."""
    exp = E.outlook(sc, avg)
    p = panel.loc[exp.index]
    ph = E.phase(p["leg_dir"], p["leg_progress"], p["ret5"])
    d = pd.DataFrame({"v": E.journey_verdict(exp, ph), "f": fwd.reindex(exp.index)}).dropna()
    d = d[d.index.get_level_values("symbol").isin(universe)]
    rows = []
    for v in ["Buy", "Neutral", "Sell"]:
        f = d.loc[d["v"] == v, "f"]
        rows.append({"verdict": v, "n": int(len(f)), "share": float(len(f) / len(d)),
                     "rose": float((f > 0).mean()), "median": float(f.median()),
                     "avg": float(f.clip(-0.3, 0.3).mean()),
                     "up3": float((f > 0.03).mean()), "down3": float((f < -0.03).mean())})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="final", choices=["final", "prelim"])
    ap.add_argument("--out", default=SITE_DATA)
    args = ap.parse_args()
    warnings.simplefilter("ignore")

    m = prep.load()
    log(f"loaded {len(m.symbols)} symbols x {len(m.dates)} days; {len(m.actions)} bonus/dividend adjustments")
    panel, ex = features.build(m)
    log(f"features: {panel.shape[1]} columns")

    key = "short"
    hz = features.HORIZONS[key]
    days, thr = hz["days"], hz["thr"]
    equities = m.info.index[m.info["is_equity"]]
    shares = m.info.index[m.info["is_equity"] & ~m.info["is_fund"]]
    btype, info = ex["btype"], m.info
    fwd_wide = ex["fwd"][key]
    fwd = fwd_wide.stack(future_stack=True).reindex(panel.index)
    hist = fwd_wide[equities].stack()

    # ---- calibrated odds, walk-forward (unseen) and live
    oos = model.smooth(model.walk_forward(panel, fwd, thr, days, m.dates))
    cal = model.Calibrator().fit(oos, fwd, thr, float((hist > thr).mean()), float((hist < -thr).mean()))
    live = model.fit(panel, fwd, thr, m.dates[-days - 1])
    avg = E.outcome_averages(fwd_wide, equities, thr)
    log(f"average move when up {avg['up']:+.1%}, when down {avg['down']:+.1%}, otherwise {avg['flat']:+.1%}")

    # ---- honest checks: portfolio every 2 weeks, and how each verdict turned out
    rebal = backtest.rebalance_dates(oos.index, m, days)
    tabs = {d: build_table(model.day_table(cal.apply(oos.xs(d, level="date")), panel.xs(d, level="date"), btype.loc[d], info),
                           panel.xs(d, level="date"), avg) for d in rebal}
    wk, calib, summary = backtest.run(m, ex, key, days, thr, tabs, "exp", *BUCKETS)
    vcheck = verdict_check(cal.apply(oos), panel, fwd, avg, shares)
    log(f"top20 {summary['top20_total']:+.1%} vs market {summary['market_total']:+.1%}, "
        f"all shares {summary['all_total']:+.1%} ({summary['periods']} periods of 2 weeks)")
    for r in vcheck:
        log(f"  {r['verdict']:11s} {r['share']:5.1%} of cases: rose {r['rose']:.0%}, median {r['median']:+.2%}, avg {r['avg']:+.2%}")

    # ---- live scoring
    q25, q50, q75 = E.path_quantiles(fwd_wide, days)

    def score_days(rows):
        prob = cal.apply(model.smooth(model.predict(live, rows)))
        out = {}
        for d in prob.index.get_level_values("date").unique():
            pd_ = panel.xs(d, level="date")
            t = build_table(model.day_table(prob.xs(d, level="date"), pd_, btype.loc[d], info), pd_, avg)
            # projected path: expected move with the share's usual spread around it
            t["path_lo"] = t["exp"] + (q25 - q50).reindex(t.index).fillna(0)
            t["path_hi"] = t["exp"] + (q75 - q50).reindex(t.index).fillna(0)
            out[d] = t
        return out

    mk = E.market_path(fwd_wide, equities)
    cal_live = E.calendar_tables(mk, days)
    extra = {
        "outcomes": avg, "verdict_check": vcheck,
        "rules": {"buy_min": E.BUY_MIN, "sell_max": E.SELL_MAX,
                  "buy_phases": sorted(E.BUY_PHASES), "sell_phases": sorted(E.SELL_PHASES)},
        "phase_text": E.PHASE_TEXT,
        "base": cal_live["base"], "month_raw": cal_live["month_raw"], "weekday_raw": cal_live["weekday_raw"],
        "thursday": E.thursday_stats(m.close, equities, m.dates),
    }
    H = {key: {"wk": wk, "calib": calib, "summary": summary, "score_days": score_days,
               "contrib": lambda pt: model.angle_contributions(live, pt), "extra": extra}}
    tables = report.build(m, panel, ex, H, report.mood(ex["market"]), args.out, args.run)
    log(f"site data written to {args.out}")
    save_signals(tables, m.dates[-1])
    t = tables[key]
    print(t.sort_values("rank_score", ascending=False).head(8)[["exp", "phase", "verdict", "buy", "sell", "conf"]].round(3).to_string())
    print(t["verdict"].value_counts().to_string())
    print(t["phase"].value_counts().to_string())


def save_signals(tables, date):
    parts = []
    for key, t in tables.items():
        rec = t.reindex(columns=["buy", "sell", "move", "direction", "exp", "phase", "conf", "verdict", "rank"]).round(4)
        rec = rec.reset_index(names="symbol")
        rec.insert(0, "date", str(date))
        rec.insert(2, "horizon", key)
        parts.append(rec)
    new = pd.concat(parts)[SIGNAL_COLS]
    if os.path.exists(SIGNALS_CSV):
        old = pd.read_csv(SIGNALS_CSV).reindex(columns=SIGNAL_COLS)
        new = pd.concat([old[old["date"] != str(date)], new])
    new.sort_values(["date", "horizon", "rank"], ascending=[False, False, True]).to_csv(SIGNALS_CSV, index=False)


if __name__ == "__main__":
    main()
