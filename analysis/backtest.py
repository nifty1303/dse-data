"""
Honest track record per timeframe: the model is retrained every month on data known
at the time and never sees the periods it is judged on.

Every 5 trading days the Top 20 is "bought" in equal amounts and held for the
timeframe (5 days short, 40 days long), paying COST_SIDE each way.
Short term: weeks don't overlap, so results compound into a growth curve.
Long term: 2-month holds overlap, so each weekly pick is reported on its own.
"""

import numpy as np
import pandas as pd

from . import model as M

COST_SIDE = 0.005
STEP = 5


def run(m, panel, ex, oos, key, days, thr):
    fwd, btype, mk = ex["fwd"][key], ex["btype"], m.index
    oos_s = M.smooth(oos)
    dates = sorted(oos_s.index.get_level_values("date").unique())
    rebal = [d for d in dates[::STEP] if m.dates.get_loc(d) + days < len(m.dates)]
    rows, prev, calib = [], set(), []
    for d in rebal:
        prob = oos_s.xs(d, level="date")
        t = M.day_table(prob, panel.xs(d, level="date"), btype.loc[d], m.info)
        top, _ = M.top_list(t)
        sells = M.top_list(t, cap=len(t), score="sell_score")[0]
        f = fwd.loc[d]
        # Short weeks chain into each other, so only replaced names pay costs.
        turnover = 1.0 if (not prev or days != STEP) else len(set(top) - prev) / len(top)
        cost = 2 * COST_SIDE * turnover
        i = m.dates.get_loc(d)
        rows.append({
            "date": d, "top20": f.reindex(top).mean() - cost, "cost": cost,
            "market": mk["cap_level"].iloc[i + days] / mk["cap_level"].iloc[i] - 1,
            "all_stocks": f[m.info["is_equity"]].mean(), "sell20": f.reindex(sells).mean(),
            "turnover": turnover, "hit_rate": (f.reindex(top) > 0).mean(),
            "target_rate": (f.reindex(top) > thr).mean(), "sell_fell": (f.reindex(sells) < 0).mean(),
            "picks": ",".join(top)})
        prev = set(top)
        calib.append(t.assign(fwd=f.reindex(t.index)).dropna(subset=["fwd"])[["buy", "sell", "direction", "fwd"]])
    wk = pd.DataFrame(rows).set_index("date")
    compounding = days == STEP
    if compounding:
        for c in ["top20", "market", "all_stocks", "sell20"]:
            wk[f"{c}_curve"] = (1 + wk[c]).cumprod() * 100

    cal = pd.concat(calib)
    edges = [0, .3, .45, .55, .7, 1.0001]
    names = ["Strong Sell / Sell (<30%)", "Sell side (30-45%)", "Balanced (45-55%)", "Buy side (55-70%)", "Strong Buy / Buy (70%+)"]
    buckets = pd.cut(cal["direction"], edges, labels=names, right=False)
    table = cal.groupby(buckets, observed=True).agg(
        predicted=("direction", "mean"), n=("fwd", "size"),
        rose=("fwd", lambda s: (s > thr).mean()), fell=("fwd", lambda s: (s < -thr).mean()),
        avg_return=("fwd", "mean")).reset_index().rename(columns={"direction": "bucket"})
    table["realized_split"] = table["rose"] / (table["rose"] + table["fell"]).replace(0, np.nan)

    def total(col):
        return float(wk[f"{col}_curve"].iloc[-1] / 100 - 1) if compounding else float(wk[col].mean())
    summary = {
        "compounding": compounding, "periods": int(len(wk)),
        "start": str(wk.index[0]), "end": str(wk.index[-1]),
        "top20_total": total("top20"), "market_total": total("market"),
        "all_total": total("all_stocks"), "sell20_total": total("sell20"),
        "beat_market": float((wk["top20"] > wk["market"]).mean()),
        "beat_all": float((wk["top20"] > wk["all_stocks"]).mean()),
        "avg_hit_rate": float(wk["hit_rate"].mean()),
        "avg_target_rate": float(wk["target_rate"].mean()),
        "avg_sell_fell": float(wk["sell_fell"].mean()),
        "avg_turnover": float(wk["turnover"].mean()),
    }
    return wk, table, summary
