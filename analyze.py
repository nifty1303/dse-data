"""
Score every DSE share for two timeframes and build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

Short term (1 week): calibrated odds of +2% vs -2%; verdict from the Buy/Sell split.
Long term (2 months): the same odds for +10% vs -10%, turned into an expected price
change (outlook from the odds + tested cycle tilt + seasonal adjustment) that sets the
verdict: under +5% Sell, +5-15% Lean Buy, 15%+ Strong Buy.

Everything is backtested walk-forward, and today's scores are appended to
data/signals.csv (a forward record the model can never revise).
"""

import argparse
import os
import time
import warnings

import pandas as pd

from analysis import backtest, features, longterm as L, model, prep, report

SITE_DATA = "site/data"
SIGNALS_CSV = "data/signals.csv"
SIGNAL_COLS = ["date", "symbol", "horizon", "buy", "sell", "move", "direction", "exp", "conf", "verdict", "rank"]
SHORT_BUCKETS = ([0, .3, .45, .55, .7, 1.0001],
                 ["Strong Sell / Sell (<30%)", "Sell side (30-45%)", "Balanced (45-55%)", "Buy side (55-70%)", "Strong Buy / Buy (70%+)"])
LONG_BUCKETS = ([-9, 0, 0.05, 0.10, 0.15, 9],
                ["Expected fall (<0%)", "Sell: 0 to +5%", "Lean Buy: +5 to +10%", "Lean Buy: +10 to +15%", "Strong Buy: +15%+"])


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def long_table(t, outlook, tilt, season):
    """Turn a day table into the long-term view: expected change drives verdict and ranking."""
    t = t.copy()
    t["outlook"] = outlook.reindex(t.index)
    t["tilt"] = tilt.reindex(t.index).fillna(0)
    t["season"] = season
    t["exp"] = t["outlook"] + t["tilt"] + season
    t["verdict_pre"] = (t["outlook"] + t["tilt"]).map(L.verdict)
    t["rank_score"] = t["exp"] + 1e-5 * t["conf"]
    t["sell_score"] = -t["exp"] + 1e-5 * t["conf"]
    t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
    t["verdict"] = t["exp"].map(L.verdict)
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

    equities = m.info.index[m.info["is_equity"]]
    btype, info = ex["btype"], m.info
    H = {}
    for key, hz in features.HORIZONS.items():
        days, thr = hz["days"], hz["thr"]
        fwd_wide = ex["fwd"][key]
        fwd = fwd_wide.stack(future_stack=True).reindex(panel.index)
        hist = fwd_wide[equities].stack()
        base_buy, base_sell = float((hist > thr).mean()), float((hist < -thr).mean())
        oos = model.smooth(model.walk_forward(panel, fwd, thr, days, m.dates))
        cal = model.Calibrator().fit(oos, fwd, thr, base_buy, base_sell)
        live = model.fit(panel, fwd, thr, m.dates[-days - 1])
        rebal = backtest.rebalance_dates(oos.index, m, days)
        day_tables = {d: model.day_table(oos.xs(d, level="date"), panel.xs(d, level="date"), btype.loc[d], info)
                      for d in rebal}

        def odds_tables(rows, live=live, cal=cal):
            prob = cal.apply(model.smooth(model.predict(live, rows)))
            return {d: model.day_table(prob.xs(d, level="date"), panel.xs(d, level="date"), btype.loc[d], info)
                    for d in prob.index.get_level_values("date").unique()}

        if key == "short":
            wk, calib, summary = backtest.run(m, ex, key, days, thr, day_tables, "direction", *SHORT_BUCKETS)
            H[key] = {"wk": wk, "calib": calib, "summary": summary, "score_days": odds_tables,
                      "contrib": lambda pt, live=live: model.angle_contributions(live, pt), "extra": {}}
        else:
            y = L.excess_target(fwd_wide, equities).stack(future_stack=True).reindex(panel.index)
            avg = L.outcome_averages(fwd_wide, equities, thr)
            base, adj, by_month, samples = L.seasonality(fwd_wide, equities)
            cyc_oos = L.cycle_walk_forward(panel, y, days, m.dates)
            odds = {d: model.day_table(cal.apply(oos.xs(d, level="date")), panel.xs(d, level="date"), btype.loc[d], info)
                    for d in rebal}
            trials = []
            for w in L.BLEND_WEIGHTS:
                tabs = {d: long_table(t, L.outlook(t, avg), w * cyc_oos.xs(d, level="date"), adj[L.season_month(d)])
                        for d, t in odds.items()}
                wk, calib, summary = backtest.run(m, ex, key, days, thr, tabs, "exp", *LONG_BUCKETS)
                trials.append({"w": w, "wk": wk, "calib": calib, "summary": summary})
                log(f"long, cycle weight {w:.2f}: top20 avg {summary['top20_total']:+.2%} per 2 months "
                    f"(all shares {summary['all_total']:+.2%}, beat index {summary['beat_market']:.0%})")
            best = trials[0]
            for tr in trials[1:]:           # a cycle weight must beat the odds alone to be used
                if tr["summary"]["top20_total"] > best["summary"]["top20_total"] + 0.001:
                    best = tr
            w = best["w"]
            d_all = panel.index.get_level_values("date")
            known = (d_all <= m.dates[-days - 1]) & y.notna().values
            cyc_table = L.cycle_table(panel.loc[known, "band_all"], y[known])
            month = L.season_month(m.dates[-1])

            def long_tables(rows, odds_tables=odds_tables, w=w, cyc_table=cyc_table):
                out = {}
                for d, t in odds_tables(rows).items():
                    band = rows.xs(d, level="date")["band_all"].reindex(t.index)
                    out[d] = long_table(t, L.outlook(t, avg), w * L.cycle_values(cyc_table, band), adj[L.season_month(d)])
                return out

            H[key] = {"wk": best["wk"], "calib": best["calib"], "summary": best["summary"], "score_days": long_tables,
                      "contrib": lambda pt, live=live: model.angle_contributions(live, pt),
                      "extra": {
                          "cycle_weight": w, "outcomes": {k: round(v, 4) for k, v in avg.items()},
                          "base": round(base, 4), "season_adj": round(float(adj[month]), 4), "month": month,
                          "season_by_month": {k: round(float(v), 4) for k, v in by_month.items()},
                          "season_samples": {k: round(float(v), 4) for k, v in samples.items()},
                          "cycle_table": {k: round(float(v), 4) for k, v in cyc_table.items()},
                          "trials": [{"w": t["w"], "top20": round(t["summary"]["top20_total"], 4),
                                      "all": round(t["summary"]["all_total"], 4),
                                      "beat_market": round(t["summary"]["beat_market"], 3)} for t in trials]}}
            log(f"long: using cycle weight {w:.2f}; season adj for month {month}: {adj[month]:+.2%}")
        s = H[key]["summary"]
        log(f"{key}: top20 {s['top20_total']:+.1%} vs market {s['market_total']:+.1%}, "
            f"all shares {s['all_total']:+.1%} ({s['periods']} periods)")

    tables = report.build(m, panel, ex, H, report.mood(ex["market"]), args.out, args.run)
    log(f"site data written to {args.out}")
    save_signals(tables, m.dates[-1])
    for key, t in tables.items():
        cols = ["buy", "sell", "move", "verdict", "conf"] + (["exp"] if "exp" in t else [])
        print(key, t.sort_values("rank_score", ascending=False).head(5)[cols].round(3).to_string(), sep="\n")
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
        old = pd.read_csv(SIGNALS_CSV)
        old = old.reindex(columns=SIGNAL_COLS)          # older files lack the "exp" column
        new = pd.concat([old[old["date"] != str(date)], new])
    new.sort_values(["date", "horizon", "rank"], ascending=[False, False, True]).to_csv(SIGNALS_CSV, index=False)


if __name__ == "__main__":
    main()
