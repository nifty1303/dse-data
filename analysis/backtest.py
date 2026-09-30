"""
Honest track record: the model is retrained every month on data known at the
time and never sees the weeks it is judged on.

Paper portfolio: every 5 trading days buy the Top 20 (equal weight), hold one
week, pay COST_SIDE on the part of the portfolio that changes on each side.
"""

import numpy as np
import pandas as pd

from . import model as M
from .features import HORIZON

COST_SIDE = 0.005


def daily_table(date, prob, panel_day, btype_day, info):
    t = pd.DataFrame(index=prob.index)
    t[["sell", "hold", "buy"]] = prob[["sell", "hold", "buy"]]
    t["sector"] = info["sector"].reindex(t.index)
    t["conf"] = M.confidence(panel_day, prob, btype_day.reindex(t.index))
    t["rank_score"] = M.rank_score(t["buy"], t["sell"], t["conf"])
    t["sell_score"] = M.sell_score(t["buy"], t["sell"], t["conf"])
    return t


def run(m, panel, ex, oos):
    fwd, btype, mk = ex["fwd"], ex["btype"], m.index
    oos_s = M.smooth(oos)
    days = sorted(oos_s.index.get_level_values("date").unique())
    rebal = [d for d in days[::HORIZON] if d in fwd.index and fwd.loc[d].notna().any()]
    rebal = [d for d in rebal if m.dates.get_loc(d) + HORIZON < len(m.dates)]
    rows, prev, calib = [], set(), []
    for d in rebal:
        prob = oos_s.xs(d, level="date")
        pday = panel.xs(d, level="date").reindex(prob.index)
        t = daily_table(d, prob, pday, btype.loc[d], m.info)
        top, _ = M.top_list(t)
        sells = M.top_list(t, cap=len(t), score="sell_score")[0]
        f = fwd.loc[d]
        turnover = 1.0 if not prev else len(set(top) - prev) / len(top)
        gross = f.reindex(top).mean()
        i = m.dates.get_loc(d)
        mkt = mk["cap_level"].iloc[i + HORIZON] / mk["cap_level"].iloc[i] - 1
        allstk = f[m.info["is_equity"]].mean()
        rows.append({"date": d, "top20_gross": gross, "cost": 2 * COST_SIDE * turnover,
                     "top20": gross - 2 * COST_SIDE * turnover, "market": mkt, "all_stocks": allstk,
                     "sell20": f.reindex(sells).mean(), "turnover": turnover,
                     "hit_rate": (f.reindex(top) > 0).mean(), "sell_fell": (f.reindex(sells) < 0).mean(),
                     "picks": ",".join(top)})
        prev = set(top)
        cb = t.assign(fwd=f.reindex(t.index)).dropna(subset=["fwd"])
        calib.append(cb[["buy", "sell", "fwd"]])
    wk = pd.DataFrame(rows).set_index("date")
    for c in ["top20", "market", "all_stocks", "sell20", "top20_gross"]:
        wk[f"{c}_curve"] = (1 + wk[c]).cumprod() * 100
    cal = pd.concat(calib)
    buckets = pd.cut(cal["buy"], [0, .2, .3, .4, .5, .6, 1.0])
    table = cal.groupby(buckets, observed=True).agg(
        predicted=("buy", "mean"), realized=("fwd", lambda s: (s > M.BUY_T).mean()),
        avg_return=("fwd", "mean"), n=("fwd", "size")).reset_index(drop=True)
    table["bucket"] = ["0-20%", "20-30%", "30-40%", "40-50%", "50-60%", "60%+"][:len(table)]
    summary = {
        "weeks": int(len(wk)),
        "start": str(wk.index[0]), "end": str(wk.index[-1]),
        "top20_total": float(wk["top20_curve"].iloc[-1] / 100 - 1),
        "market_total": float(wk["market_curve"].iloc[-1] / 100 - 1),
        "all_total": float(wk["all_stocks_curve"].iloc[-1] / 100 - 1),
        "sell20_total": float(wk["sell20_curve"].iloc[-1] / 100 - 1),
        "avg_week_top20": float(wk["top20"].mean()),
        "avg_week_market": float(wk["market"].mean()),
        "beat_market_weeks": float((wk["top20"] > wk["market"]).mean()),
        "positive_weeks": float((wk["top20"] > 0).mean()),
        "avg_turnover": float(wk["turnover"].mean()),
        "avg_hit_rate": float(wk["hit_rate"].mean()),
        "avg_sell_fell": float(wk["sell_fell"].mean()),
    }
    return wk, table, summary
