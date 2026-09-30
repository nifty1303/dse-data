"""
Score every DSE share for the next 2 weeks (10 trading days) and build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

For each share: calibrated odds of a >3% rise vs a >3% fall, turned into an expected
2-week change (odds outlook + cycle tilt + month season + weekday effect). Each add-on
is kept only if the walk-forward backtest shows it helps. Verdict: under +1% Sell,
+1% to +2.5% Lean Buy, +2.5% to +4% Buy, +4% or more Strong Buy.

Today's scores are appended to data/signals.csv (a forward record the model can
never revise).
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
SIGNAL_COLS = ["date", "symbol", "horizon", "buy", "sell", "move", "direction", "exp", "conf", "verdict", "rank"]
BUCKETS = ([-9, 0, 0.01, 0.025, 0.04, 9],
           ["Expected fall (<0%)", "Sell: 0 to +1%", "Lean Buy: +1 to +2.5%", "Buy: +2.5 to +4%", "Strong Buy: +4%+"])


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def build_table(t, outlook, tilt, month_adj, wday_adj):
    """Day table -> expected change, verdict and ranking."""
    t = t.copy()
    t["outlook"] = outlook.reindex(t.index)
    t["tilt"] = tilt.reindex(t.index).fillna(0)
    t["season"] = month_adj
    t["weekday_adj"] = wday_adj
    t["exp"] = t["outlook"] + t["tilt"] + month_adj + wday_adj
    t["verdict_pre"] = (t["outlook"] + t["tilt"]).map(E.verdict)
    t["rank_score"] = t["exp"] + 1e-5 * t["conf"]
    t["sell_score"] = -t["exp"] + 1e-5 * t["conf"]
    t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
    t["verdict"] = t["exp"].map(E.verdict)
    return t


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
    btype, info = ex["btype"], m.info
    fwd_wide = ex["fwd"][key]
    fwd = fwd_wide.stack(future_stack=True).reindex(panel.index)
    hist = fwd_wide[equities].stack()

    # ---- calibrated odds, walk-forward
    oos = model.smooth(model.walk_forward(panel, fwd, thr, days, m.dates))
    cal = model.Calibrator().fit(oos, fwd, thr, float((hist > thr).mean()), float((hist < -thr).mean()))
    live = model.fit(panel, fwd, thr, m.dates[-days - 1])
    rebal = backtest.rebalance_dates(oos.index, m, days)
    odds = {d: model.day_table(cal.apply(oos.xs(d, level="date")), panel.xs(d, level="date"), btype.loc[d], info)
            for d in rebal}
    avg = E.outcome_averages(fwd_wide, equities, thr)
    log(f"odds ready; average move when up {avg['up']:+.1%}, when down {avg['down']:+.1%}, otherwise {avg['flat']:+.1%}")

    # ---- add-on 1: cycle tilt (changes the order of shares -> judged on the Top 20)
    y = E.excess_target(fwd_wide, equities).stack(future_stack=True).reindex(panel.index)
    cyc_oos = E.cycle_walk_forward(panel, y, days, m.dates)

    def run(w, calendar=None):
        tabs = {}
        for d, t in odds.items():
            ma, wa = calendar(d) if calendar else (0.0, 0.0)
            tabs[d] = build_table(t, E.outlook(t, avg), w * cyc_oos.xs(d, level="date"), ma, wa)
        return tabs, backtest.run(m, ex, key, days, thr, tabs, "exp", *BUCKETS)

    trials = []
    for w in [0.0] + E.CYCLE_WEIGHTS:
        _, (wk, _, s) = run(w)
        trials.append({"w": w, "top20": s["top20_total"], "all": s["all_total"], "beat_market": s["beat_market"]})
        log(f"cycle weight {w:.2f}: top20 {s['top20_total']:+.2%} (all shares {s['all_total']:+.2%}, beat index {s['beat_market']:.0%})")
    best = trials[0]
    for tr in trials[1:]:
        if tr["top20"] > best["top20"] + 0.002:
            best = tr
    w = best["w"]

    # ---- add-ons 2-3: month season and weekday effect (move every share equally ->
    # judged on how close the average expected change comes to what happened)
    mk = E.market_path(fwd_wide, equities)
    cal_tabs = {d: E.calendar_tables(mk, days, until=m.dates[m.dates.get_loc(d) - days - 1]) for d in rebal}
    realized = {d: fwd_wide.loc[d, equities].clip(*E.CLIP).mean() for d in rebal}

    def level_error(use_month, use_weekday):
        tabs, _ = run(w, lambda d: E.calendar_adjust(cal_tabs[d], d, days, use_month, use_weekday))
        err = [tabs[d].loc[tabs[d].index.intersection(equities), "exp"].mean() - realized[d] for d in rebal]
        return float(np.sqrt(np.nanmean(np.square(err)))), float(np.nanmean(err))

    cal_trials = {}
    for name, flags in {"none": (False, False), "month": (True, False), "weekday": (False, True), "both": (True, True)}.items():
        rmse, bias = level_error(*flags)
        cal_trials[name] = {"rmse": rmse, "bias": bias}
        log(f"calendar {name:7s}: error of expected 2-week market move {rmse:.2%} (bias {bias:+.2%})")
    use_month = cal_trials["month"]["rmse"] < cal_trials["none"]["rmse"] - 0.0005
    base_name = "month" if use_month else "none"
    with_wday = "both" if use_month else "weekday"
    use_weekday = cal_trials[with_wday]["rmse"] < cal_trials[base_name]["rmse"] - 0.0005
    log(f"using: cycle weight {w}, month season {use_month}, weekday effect {use_weekday}")

    tabs, (wk, calib, summary) = run(w, lambda d: E.calendar_adjust(cal_tabs[d], d, days, use_month, use_weekday))
    log(f"top20 {summary['top20_total']:+.1%} vs market {summary['market_total']:+.1%}, "
        f"all shares {summary['all_total']:+.1%} ({summary['periods']} periods of 2 weeks)")

    # ---- live scoring
    d_all = panel.index.get_level_values("date")
    known = (d_all <= m.dates[-days - 1]) & y.notna().values
    cyc_table = E.cycle_table(panel.loc[known, "band_all"], y[known])
    cal_live = E.calendar_tables(mk, days, until=m.dates[-days - 1])

    def score_days(rows):
        prob = cal.apply(model.smooth(model.predict(live, rows)))
        out = {}
        for d in prob.index.get_level_values("date").unique():
            t = model.day_table(prob.xs(d, level="date"), panel.xs(d, level="date"), btype.loc[d], info)
            band = rows.xs(d, level="date")["band_all"].reindex(t.index)
            ma, wa = E.calendar_adjust(cal_live, d, days, use_month, use_weekday)
            out[d] = build_table(t, E.outlook(t, avg), w * E.cycle_values(cyc_table, band), ma, wa)
        return out

    today = m.dates[-1]
    extra = {
        "cycle_weight": w, "trials": trials, "outcomes": avg,
        "use_month": bool(use_month), "use_weekday": bool(use_weekday), "calendar_trials": cal_trials,
        "base": cal_live["base"], "month_raw": cal_live["month_raw"], "month_n": cal_live["month_n"],
        "weekday_raw": cal_live["weekday_raw"],
        "month_now": E.season_month(today, days), "weekday_now": E.weekday(today),
        "month_adj_now": cal_live["month"].get(E.season_month(today, days), 0.0) if use_month else 0.0,
        "weekday_adj_now": cal_live["weekday"].get(E.weekday(today), 0.0) if use_weekday else 0.0,
        "thursday": E.thursday_stats(m.close, equities, m.dates),
        "cycle_table": {k: float(v) for k, v in cyc_table.items()},
    }
    H = {key: {"wk": wk, "calib": calib, "summary": summary, "score_days": score_days,
               "contrib": lambda pt: model.angle_contributions(live, pt), "extra": extra}}
    tables = report.build(m, panel, ex, H, report.mood(ex["market"]), args.out, args.run)
    log(f"site data written to {args.out}")
    save_signals(tables, today)
    t = tables[key]
    print(t.sort_values("rank_score", ascending=False).head(8)[["buy", "sell", "move", "exp", "outlook", "tilt", "verdict", "conf"]].round(3).to_string())
    print(t["verdict"].value_counts().to_string())


def save_signals(tables, date):
    parts = []
    for key, t in tables.items():
        rec = t.reindex(columns=["buy", "sell", "move", "direction", "exp", "conf", "verdict", "rank"]).round(4)
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
