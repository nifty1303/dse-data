"""
Score every DSE share for two timeframes and build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

Steps: load + adjust prices -> features -> per timeframe (1 week, 2 months):
walk-forward backtest -> live model -> calibrated Buy/Sell odds -> JSON for the
site, and today's scores appended to data/signals.csv (a forward record the
model can never revise).
"""

import argparse
import os
import time
import warnings

import pandas as pd

from analysis import backtest, features, model, prep, report

SITE_DATA = "site/data"
SIGNALS_CSV = "data/signals.csv"
SIGNAL_COLS = ["date", "symbol", "horizon", "buy", "sell", "move", "direction", "conf", "verdict", "rank"]


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.1f}s] {msg}", flush=True)


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
    H = {}
    for key, hz in features.HORIZONS.items():
        days, thr = hz["days"], hz["thr"]
        fwd_wide = ex["fwd"][key]
        fwd = fwd_wide.stack(future_stack=True).reindex(panel.index)
        hist = fwd_wide[equities].stack()
        base_buy, base_sell = float((hist > thr).mean()), float((hist < -thr).mean())
        oos = model.walk_forward(panel, fwd, thr, days, m.dates)
        wk, calib, summary = backtest.run(m, panel, ex, oos, key, days, thr)
        live = model.fit(panel, fwd, thr, m.dates[-days - 1])
        cal = model.Calibrator().fit(model.smooth(oos), fwd, thr, base_buy, base_sell)
        H[key] = {"live": live, "cal": cal, "wk": wk, "calib": calib, "summary": summary}
        log(f"{key}: top20 {summary['top20_total']:+.1%} vs market {summary['market_total']:+.1%}, "
            f"all shares {summary['all_total']:+.1%} ({summary['periods']} periods)")

    tables = report.build(m, panel, ex, H, report.mood(ex["market"]), args.out, args.run)
    log(f"site data written to {args.out}")
    save_signals(tables, m.dates[-1])
    for key, t in tables.items():
        print(key, t.sort_values("rank_score", ascending=False).head(5)[["buy", "sell", "move", "verdict", "conf"]].round(2).to_string(), sep="\n")


def save_signals(tables, date):
    parts = []
    for key, t in tables.items():
        rec = t[["buy", "sell", "move", "direction", "conf", "verdict", "rank"]].round(4).reset_index(names="symbol")
        rec.insert(0, "date", str(date))
        rec.insert(2, "horizon", key)
        parts.append(rec)
    new = pd.concat(parts)[SIGNAL_COLS]
    if os.path.exists(SIGNALS_CSV):
        old = pd.read_csv(SIGNALS_CSV)
        if list(old.columns) == SIGNAL_COLS:       # older single-timeframe files are replaced
            new = pd.concat([old[old["date"] != str(date)], new])
    new.sort_values(["date", "horizon", "rank"], ascending=[False, False, True]).to_csv(SIGNALS_CSV, index=False)


if __name__ == "__main__":
    main()
