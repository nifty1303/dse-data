"""
Honest track record per timeframe: the model is retrained every month on data known
at the time and never sees the periods it is judged on.

Every holding period (one month = 20 trading days) the Top 20 is "bought" in equal
amounts. With a profit goal, each share is sold as soon as it closes at +goal, otherwise
at the end of the month; COST_SIDE is paid each way on the part of the list that changes.
Periods follow each other without overlap, so results compound into a growth curve.
"""

import numpy as np
import pandas as pd

from . import model as M

COST_SIDE = 0.005


def rebalance_dates(oos_index, m, days):
    dates = sorted(oos_index.get_level_values("date").unique())
    return [d for d in dates[::days] if m.dates.get_loc(d) + days < len(m.dates)]


def run(m, ex, key, days, thr, tables, calib_col, calib_edges, calib_names, goal=None, result=None, label=None):
    """tables: {date: day table with sector, rank_score, sell_score and calib_col}."""
    fwd, mk = ex["fwd"][key], m.index
    fmax = ex["fwd_max"][key]
    rows, prev, calib = [], set(), []
    for d, t in tables.items():
        top, _ = M.top_list(t)
        sells = M.top_list(t, cap=len(t), score="sell_score")[0]
        f_end = fwd.loc[d]
        if result is not None:
            f = result.loc[d]                                   # trade result of the exit rule (e.g. +5% / -5% race)
        else:
            f = f_end.where(fmax.loc[d] < goal, goal) if goal else f_end   # sell at the goal when touched
        # Periods chain into each other, so only replaced names pay costs.
        turnover = 1.0 if not prev else len(set(top) - prev) / len(top)
        cost = 2 * COST_SIDE * turnover
        i = m.dates.get_loc(d)
        rows.append({
            "date": d, "top20": f.reindex(top).mean() - cost, "cost": cost,
            "market": mk["cap_level"].iloc[i + days] / mk["cap_level"].iloc[i] - 1,
            "all_stocks": f[m.info["is_equity"]].mean(), "sell20": f.reindex(sells).mean(),
            "all_hold": f_end[m.info["is_equity"]].mean(),
            "hold_end": f_end.reindex(top).mean() - cost,
            "goal_rate": (fmax.loc[d].reindex(top) >= goal).mean() if goal else float("nan"),
            "turnover": turnover, "hit_rate": (f.reindex(top) > 0).mean(),
            "target_rate": (f.reindex(top) >= thr - 1e-9).mean(), "sell_fell": (f.reindex(sells) < 0).mean(),
            "stop_rate": ((label.loc[d] if label is not None else -(f <= -thr + 1e-9).astype(float)).reindex(top) == -1).mean(),
            "sell_stop": ((label.loc[d] if label is not None else -(f <= -thr + 1e-9).astype(float)).reindex(sells) == -1).mean(),
            "picks": ",".join(top)})
        prev = set(top)
        calib.append(t.assign(fwd=f.reindex(t.index)).dropna(subset=["fwd"])[[calib_col, "fwd"]])
    wk = pd.DataFrame(rows).set_index("date")
    compounding = True
    if compounding:
        for c in ["top20", "market", "all_stocks", "sell20", "hold_end", "all_hold"]:
            wk[f"{c}_curve"] = (1 + wk[c]).cumprod() * 100

    cal = pd.concat(calib)
    buckets = pd.cut(cal[calib_col], calib_edges, labels=calib_names, right=False)
    table = cal.groupby(buckets, observed=True).agg(
        predicted=(calib_col, "mean"), n=("fwd", "size"),
        rose=("fwd", lambda s: (s >= thr - 1e-9).mean()), fell=("fwd", lambda s: (s <= -thr + 1e-9).mean()),
        avg_return=("fwd", "mean"), median_return=("fwd", "median")).reset_index().rename(columns={calib_col: "bucket"})
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
        "hold_end_total": total("hold_end"),
        "avg_goal_rate": float(wk["goal_rate"].mean()),
        "all_hold_total": total("all_hold"),
        "avg_stop_rate": float(wk["stop_rate"].mean()), "avg_sell_stop": float(wk["sell_stop"].mean()),
    }
    return wk, table, summary
