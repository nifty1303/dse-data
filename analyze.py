"""
Score every DSE share and build the website data.

    python analyze.py                 # full run, writes site/data/
    python analyze.py --run prelim    # label the page as the 3 PM preliminary update

Steps: load + adjust prices -> features -> walk-forward backtest -> live model
-> calibrated Buy/Hold/Sell -> JSON for the site, and today's scores appended
to data/signals.csv (a forward record the model can never revise).
"""

import argparse
import os
import time
import warnings

import pandas as pd

from analysis import backtest, features, model, prep, report

SITE_DATA = "site/data"
SIGNALS_CSV = "data/signals.csv"


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

    fwd = ex["fwd"].stack(future_stack=True).reindex(panel.index)
    oos = model.walk_forward(panel, fwd, m.dates)
    wk, calib, summary = backtest.run(m, panel, ex, oos)
    log(f"backtest: {summary['weeks']} weeks, top20 {summary['top20_total']:+.1%}, "
        f"market {summary['market_total']:+.1%}, all shares {summary['all_total']:+.1%}")

    live = model.fit(panel, fwd, m.dates[-features.HORIZON - 1])
    cal = model.Calibrator().fit(model.smooth(oos), fwd)
    t = report.build(m, panel, ex, live, cal, oos, wk, calib, summary, args.out, args.run)
    log(f"site data written to {args.out}")

    save_signals(t, m.dates[-1])
    top = t.sort_values("rank_score", ascending=False).head(10)
    print(top[["sector", "buy", "hold", "sell", "conf"]].round(2).to_string())


def save_signals(t, date):
    rec = t[["buy", "hold", "sell", "conf", "rank"]].round(4).reset_index(names="symbol")
    rec.insert(0, "date", str(date))
    if os.path.exists(SIGNALS_CSV):
        old = pd.read_csv(SIGNALS_CSV)
        rec = pd.concat([old[old["date"] != str(date)], rec])
    rec.sort_values(["date", "rank"], ascending=[False, True]).to_csv(SIGNALS_CSV, index=False)


if __name__ == "__main__":
    main()
