"""
Score every DSE share for the next month (20 trading days, e.g. 1 Oct -> 1 Nov) and
build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

The plan is a race: buy today, sell at the share's own take-profit (at least +5%, up to its
nearest resistance) or at its own stop-loss (from its supports and volatility), whichever close comes first, or at the end of the month. For each share:
- calibrated chances that the target comes first / the stop comes first / neither
- expected trade result after ~1% round-trip costs
- tag from fixed levels: Buy when the lead (target-first minus stop-first chance) is +15 or
  more (+25 for junk shares), the price is below its 2-year average and the share is not
  Topping or in a Mid fall; Sell when the stop is more likely first while the price is at or
  above its 2-year average, or the price is 20%+ above that average without a +15 lead
- journey, trade plan (buy zone, target, stop, sell-by date) and projected range

Everything is checked walk-forward on periods the model never saw, and today's scores
are appended to data/signals.csv (a forward record the model can never revise).
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
SIGNAL_COLS = ["date", "symbol", "horizon", "buy", "sell", "move", "direction", "exp", "hit", "phase", "conf", "verdict", "rank"]
BUCKETS = ([-9, 0, 0.1, 0.2, 0.3, 9], ["Below 0 (stop more likely)", "0 to +10 pts", "+10 to +20 pts", "+20 to +30 pts", "+30 pts or more"])


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def build_table(t, panel_day, goal, flat_avg):
    """Day table (buy = target-first chance, sell = stop-first chance) -> trade value, tag, ranking."""
    t = t.copy()
    p = panel_day.reindex(t.index)
    t["hit"], t["stop_p"] = t["buy"], t["sell"]
    t["stop_dist"] = p["stop_dist"].fillna(0.08)
    t["target_dist"] = p["target_dist"].fillna(goal)
    t["value"] = E.trade_value(t["buy"], t["sell"], t["target_dist"], t["stop_dist"], flat_avg)
    t["exp"] = t["value"] + E.COST                                               # gross expected result
    t["phase"] = E.phase(p["leg_dir"], p["leg_progress"], p["ret5"])
    t["junk"] = p["type_junk"].fillna(0) > 0
    t["dev2y"], t["band_all"] = p["dev2y"], p["band_all"]
    t["lead"] = t["buy"] - t["sell"]
    t["verdict"] = E.race_tag(t["buy"], t["sell"], t["phase"], t["junk"], t["dev2y"].fillna(0))
    t["tier"] = t["verdict"].map(E.TIER)
    t["rank_score"] = t["tier"] + t["lead"] + 1e-6 * t["conf"]
    t["sell_score"] = (2 - t["tier"]) - t["lead"] + 1e-6 * t["conf"]
    t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
    return t


def tag_check(tables_all, lab, res, universe):
    """How each tag turned out on unseen days, trading the +5% / -5% race."""
    d = pd.concat([t[["verdict"]].assign(date=k) for k, t in tables_all.items()])
    d = d.set_index("date", append=True).swaplevel()
    d.index.names = ["date", "symbol"]
    d["lab"], d["res"] = lab.reindex(d.index), res.reindex(d.index)
    d = d.dropna()
    d = d[d.index.get_level_values("symbol").isin(universe)]
    rows = []
    for v in ["Buy", "Neutral", "Sell"]:
        x = d[d["verdict"] == v]
        rows.append({"verdict": v, "n": int(len(x)), "share": float(len(x) / len(d)),
                     "target": float((x["lab"] == 1).mean()), "stop": float((x["lab"] == -1).mean()),
                     "neither": float((x["lab"] == 0).mean()), "gross": float(x["res"].mean()),
                     "net": float(x["res"].mean() - E.COST)})
    return rows


def edge_deciles(tables_all, lab, res, universe):
    """Every unseen day, shares split into 10 equal groups by lead (target-first minus stop-first chance)."""
    d = pd.concat([t[["buy", "sell"]].assign(date=k) for k, t in tables_all.items()])
    d = d.set_index("date", append=True).swaplevel()
    d.index.names = ["date", "symbol"]
    d["lab"], d["res"] = lab.reindex(d.index), res.reindex(d.index)
    d = d.dropna()
    d = d[d.index.get_level_values("symbol").isin(universe)]
    d["edge"] = d["buy"] - d["sell"]
    d["q"] = d.groupby(level="date")["edge"].transform(lambda x: np.floor(x.rank(pct=True, method="first") * 10 - 1e-9))
    rows = []
    for q, x in d.groupby("q"):
        rows.append({"group": int(q) + 1, "n": int(len(x)), "edge": float(x["edge"].mean()),
                     "target": float((x["lab"] == 1).mean()), "stop": float((x["lab"] == -1).mean()),
                     "gross": float(x["res"].mean()), "net": float(x["res"].mean() - E.COST)})
    return rows[::-1]


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
    days, goal = hz["days"], hz["thr"]
    equities = m.info.index[m.info["is_equity"]]
    shares = m.info.index[m.info["is_equity"] & ~m.info["is_fund"]]
    btype, info = ex["btype"], m.info
    stop_w, tgt_w = ex["wide"]["stop_dist"], ex["wide"]["target_dist"]
    lab_w, res_w = E.race(m.close, days, tgt_w, stop_w)
    lab, res = lab_w.stack(future_stack=True).reindex(panel.index), res_w.stack(future_stack=True).reindex(panel.index)
    le, re_ = lab_w[equities].stack(), res_w[equities].stack()
    base_t, base_s = float((le == 1).mean()), float((le == -1).mean())
    flat_avg = float(re_[le == 0].mean())
    log(f"race own target (median {tgt_w[equities].stack().median():.1%}) vs own stop (median {stop_w[equities].stack().median():.1%}) over {days} sessions: target first {base_t:.0%}, stop first {base_s:.0%}, "
        f"neither {1 - base_t - base_s:.0%} (avg {flat_avg:+.1%})")

    # ---- calibrated race odds, walk-forward (unseen) and live
    oos = model.smooth_race(model.walk_forward_race(panel, lab, days, m.dates))
    rcal = model.RaceCalibrator().fit(oos, lab, base_t, base_s)
    live = model.fit_race(panel, lab, m.dates[-days - 1])

    def odds(raw):
        c = rcal.apply(raw)
        return pd.DataFrame({"sell": c["stop"], "flat": 1 - c["stop"] - c["target"], "buy": c["target"]}, index=raw.index)

    # ---- honest checks on unseen days
    oos_c = odds(oos)
    oos_days = sorted(oos.index.get_level_values("date").unique())
    tables_all = {d: build_table(model.day_table(oos_c.xs(d, level="date"), panel.xs(d, level="date"), btype.loc[d], info),
                                 panel.xs(d, level="date"), goal, flat_avg) for d in oos_days}
    rebal = backtest.rebalance_dates(oos.index, m, days)
    wk, calib, summary = backtest.run(m, ex, key, days, goal, {d: tables_all[d] for d in rebal}, "lead", *BUCKETS, result=res_w, label=lab_w)
    tcheck = tag_check(tables_all, lab, res, shares)
    deciles = edge_deciles(tables_all, lab, res, shares)
    for r in deciles:
        log(f"  group {r['group']:2d}: lead {r['edge']:+.2f}, target {r['target']:.0%}, stop {r['stop']:.0%}, net {r['net']:+.2%}")
    log(f"top20 race trades {summary['top20_total']:+.1%} after costs vs market {summary['market_total']:+.1%}, "
        f"all shares {summary['all_total']:+.1%} ({summary['periods']} months)")
    for r in tcheck:
        log(f"  {r['verdict']:8s} {r['share']:5.1%}: target first {r['target']:.0%}, stop first {r['stop']:.0%}, "
            f"avg trade {r['gross']:+.2%} before costs, {r['net']:+.2%} after")

    # ---- live scoring
    fwd_wide = ex["fwd"][key]
    q25, q50, q75 = E.path_quantiles(fwd_wide, days)

    def score_days(rows):
        prob = odds(model.smooth_race(model.predict_race(live, rows)))
        out = {}
        for d in prob.index.get_level_values("date").unique():
            pd_ = panel.xs(d, level="date")
            t = build_table(model.day_table(prob.xs(d, level="date"), pd_, btype.loc[d], info), pd_, goal, flat_avg)
            t["path_lo"] = t["exp"] + (q25 - q50).reindex(t.index).fillna(0)
            t["path_hi"] = t["exp"] + (q75 - q50).reindex(t.index).fillna(0)
            out[d] = t
        return out

    mk = E.market_path(fwd_wide, equities)
    cal_live = E.calendar_tables(mk, days)
    today = m.dates[-1]
    extra = {
        "goal": goal, "buy_lead": E.BUY_LEAD, "junk_lead": E.JUNK_LEAD, "sell_dev": E.SELL_DEV, "no_buy_phases": list(E.NO_BUY_PHASES), "cost": E.COST, "base_target": base_t, "base_stop": base_s,
        "flat_avg": flat_avg, "verdict_check": tcheck, "deciles": deciles,
        "sell_by": (pd.Timestamp(today) + pd.Timedelta(days=1) + pd.DateOffset(months=1)).strftime("%Y-%m-%d"),   # bought next session
        "phase_text": E.PHASE_TEXT,
        "base": cal_live["base"], "month_raw": cal_live["month_raw"], "weekday_raw": cal_live["weekday_raw"],
        "thursday": E.thursday_stats(m.close, equities, m.dates),
    }
    H = {key: {"wk": wk, "calib": calib, "summary": summary, "score_days": score_days,
               "contrib": lambda pt: model.race_contributions(live, pt), "extra": extra}}
    tables = report.build(m, panel, ex, H, report.mood(ex["market"]), args.out, args.run)
    log(f"site data written to {args.out}")
    save_signals(tables, today)
    t = tables[key]
    print(t.sort_values("rank_score", ascending=False).head(8)[["hit", "stop_p", "stop_dist", "value", "phase", "verdict", "conf"]].round(3).to_string())
    print(t["verdict"].value_counts().to_string())


def save_signals(tables, date):
    parts = []
    for key, t in tables.items():
        rec = t.reindex(columns=["buy", "sell", "move", "direction", "exp", "hit", "phase", "conf", "verdict", "rank"]).round(4)
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
