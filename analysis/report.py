"""Turn scores into the JSON files the website reads."""

import json
import math
import os

import numpy as np
import pandas as pd

from . import model as M
from .features import ANGLES, HORIZON

TYPE_LABEL = {"cycler": "Steady cycler", "trender": "Trender", "junk": "Operator / junk",
              "dead": "Dead / illiquid", "mixed": "Mixed", "new": "New listing"}
STAGE_LABEL = {"quiet": "Quiet", "accumulation": "Accumulation", "markup": "Markup",
               "distribution": "Distribution", "dump": "Dump"}


def _r(x, n=4):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def _dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), allow_nan=False)


# ------------------------------------------------------------ market mood
def mood(market):
    last = market.iloc[-1]
    score = float(last["mood"])
    label = ("Friendly" if score > 0.3 else "Neutral" if score > 0
             else "Caution" if score > -0.3 else "Hostile")
    reasons = []
    r20 = last["mkt_ret20"]
    reasons.append(f"Market index {'up' if r20 >= 0 else 'down'} {abs(r20):.1%} over 4 weeks")
    reasons.append(f"{last['breadth']:.0%} of shares trade above their 20-day average")
    ad = last["adv_dec5"]
    reasons.append(f"Last 5 days: {'more risers than fallers' if ad > 0 else 'more fallers than risers'} "
                   f"({ad:+.0%} net)")
    tt = last["turnover_trend"]
    reasons.append(f"Turnover {'above' if tt > 0 else 'below'} its 6-month norm ({math.exp(tt) - 1:+.0%})")
    reasons.append(f"{last['near_low']:.0%} of shares sit near their regular low, "
                   f"{last['near_high']:.0%} near their regular high")
    warning = None
    if label in ("Caution", "Hostile"):
        warning = ("Market conditions are weak: most buy signals fail more often when the whole "
                   "market is falling. Consider smaller positions or waiting.")
    hist = market.tail(250)
    return {"label": label, "score": _r(score, 3), "reasons": reasons, "warning": warning,
            "metrics": {k: _r(last[k], 4) for k in ["mkt_ret5", "mkt_ret20", "breadth", "adv_dec5",
                                                   "turnover_trend", "near_low", "near_high", "turnover"]},
            "history": {"dates": [str(d) for d in hist.index], "mood": [_r(v, 3) for v in hist["mood"]],
                        "breadth": [_r(v, 3) for v in hist["breadth"]]}}


# ------------------------------------------------------------ reasons
def angle_phrase(angle, p, contrib):
    """Short human reason for an angle, given today's feature row p."""
    up = contrib > 0
    if angle == "Cycle position":
        b = p["band60"]
        where = ("below its regular low" if b < 0 else "near its regular low" if b < 0.25
                 else "above its regular high" if b > 1 else "near its regular high" if b > 0.75
                 else f"{b:.0%} up its regular range")
        leg = ""
        if p["leg_dir"] and not pd.isna(p["leg_days"]):
            typ = p["up_len"] if p["leg_dir"] == 1 else p["dn_len"]
            leg = f"; {'rising' if p['leg_dir'] == 1 else 'falling'} leg day {int(p['leg_days'])}"
            if not pd.isna(typ) and p["leg_days"] > 3 * typ:
                leg += " (unusually long run)"
            elif not pd.isna(typ):
                leg += f" of ~{int(typ)}"
        return f"Price {where}{leg}"
    if angle == "Trend & momentum":
        return f"{p['ret5']:+.1%} this week, {p['ret20']:+.1%} in 4 weeks; {p['dist_ma20']:+.1%} vs 20-day avg"
    if angle == "Money flow":
        vr = math.exp(p["vol_ratio5"]) if not pd.isna(p["vol_ratio5"]) else 1
        ud = "buyers" if p["updown_vol"] > 0 else "sellers"
        return f"Volume {vr:.1f}x normal; more volume on {ud}' days"
    if angle == "Liquidity":
        return f"Median turnover Tk {math.expm1(p['liq_value']):.1f} mn/day" if not pd.isna(p["liq_value"]) else "Thin trading"
    if angle == "Risk":
        s = f"Daily swing {p['vol20']:.1%}" if not pd.isna(p["vol20"]) else "Risk"
        if p["uc_hits20"] > 0:
            s += f"; {int(p['uc_hits20'])} upper-circuit hits in 4 weeks"
        if p["drawdown120"] < -0.2:
            s += f"; {p['drawdown120']:.0%} below 6-month high"
        return s
    if angle == "Relative strength":
        return f"{p['rel_mkt20']:+.1%} vs market, {p['rel_sec20']:+.1%} vs sector (4 weeks)"
    if angle == "Market mood":
        return f"Market mood {'supports' if up else 'weighs on'} shares like this"
    if angle == "Fundamentals":
        cat = "A" if p["cat_A"] else "B" if p["cat_B"] else "Z" if p["cat_Z"] else "N/other"
        s = f"Category {cat}; sponsors hold {p['sponsor_pct']:.0%}"
        if p["reserve_neg"]:
            s += "; negative reserves"
        return s
    if angle == "Junk pattern":
        stage = next((k.title() for k in ["markup", "distribution", "dump", "accumulation"] if p[f"stage_{k}"]), None)
        j = p["junk_score"]
        s = ("Low junk risk" if j < 0.4 else "High junk risk" if j >= 0.62 else "Some junk traits") + f" (score {j:.0%})"
        return s + (f"; {stage} stage" if stage else "")
    if angle == "Similar setups":
        if pd.isna(p["analog_ret"]):
            return "Not enough similar past setups"
        return f"Similar past setups: {p['analog_ret']:+.1%} avg next week, {p['analog_win']:.0%} rose"
    return angle


def reasons(p, contrib_row, side="buy", n=3):
    # Market mood is the same for every share, so it explains nothing about this one.
    s = (contrib_row if side == "buy" else -contrib_row).drop("Market mood")
    top = s[s > 0.3].sort_values(ascending=False).head(n)
    return [angle_phrase(a, p, contrib_row[a]) for a in top.index]


# ------------------------------------------------------------ main builder
def build(m, panel, ex, live, cal, oos_raw, wk, calib_table, summary, out_dir, run_kind):
    dates = m.dates
    today = dates[-1]
    recent = dates[-60:]
    info = m.info
    btype, stage = ex["btype"], ex["stage"]
    W = ex["wide"]

    rows = panel.loc[panel.index.get_level_values("date") >= recent[0]]
    raw = M.predict(live, rows)
    prob = cal.apply(M.smooth(raw))

    # daily tables for the last 60 days -> rank history
    tables, tops = {}, {}
    for d in recent:
        p = prob.xs(d, level="date")
        t = pd.DataFrame(index=p.index)
        t[["sell", "hold", "buy"]] = p[["sell", "hold", "buy"]]
        t["sector"] = info["sector"].reindex(t.index)
        t["conf"] = M.confidence(panel.xs(d, level="date").reindex(t.index), p, btype.loc[d].reindex(t.index))
        t["rank_score"] = M.rank_score(t["buy"], t["sell"], t["conf"])
        t["sell_score"] = M.sell_score(t["buy"], t["sell"], t["conf"])
        t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
        tables[d] = t
        tops[d] = M.top_list(t)[0]
    t = tables[today]
    top, also = M.top_list(t)
    yday = tables[recent[-2]]
    week_ago = tables[recent[-6]]

    def days_in_top(sym):
        n = 0
        for d in reversed(recent):
            if sym in tops[d]:
                n += 1
            else:
                break
        return n

    pt = panel.xs(today, level="date")
    contrib = M.angle_contributions(live, pt)
    close_raw = m.raw_close.iloc[-1]
    prev_raw = m.raw_close.iloc[-2]

    def row(sym, side="buy"):
        p = pt.loc[sym]
        r = t.loc[sym]
        spark = m.close[sym].iloc[-30:]
        return {
            "sym": sym, "sector": r["sector"], "cat": info.at[sym, "market_category"],
            "type": TYPE_LABEL.get(btype.at[today, sym], "Mixed"),
            "stage": STAGE_LABEL.get(stage.at[today, sym], "Quiet"),
            "close": _r(close_raw[sym], 2), "chg": _r(close_raw[sym] / prev_raw[sym] - 1, 4),
            "buy": _r(r["buy"], 3), "hold": _r(r["hold"], 3), "sell": _r(r["sell"], 3),
            "conf": int(r["conf"]), "score": _r(r["rank_score"], 4), "rank": int(r["rank"]),
            "rank_prev": int(yday.at[sym, "rank"]) if sym in yday.index else None,
            "rank_week": int(week_ago.at[sym, "rank"]) if sym in week_ago.index else None,
            "days_top": days_in_top(sym),
            "band": _r(p["band60"], 3), "up_room": _r(p["up_room"], 3), "down_risk": _r(p["down_risk"], 3),
            "leg": int(p["leg_dir"]) if not pd.isna(p["leg_dir"]) else 0,
            "leg_days": _r(p["leg_days"], 0), "leg_typ": _r(p["up_len"] if p["leg_dir"] == 1 else p["dn_len"], 0),
            "liq": _r(math.expm1(p["liq_value"]), 2) if not pd.isna(p["liq_value"]) else None,
            "junk": _r(p["junk_score"], 2),
            "reasons": reasons(p, contrib.loc[sym], side),
            "spark": [_r(v, 2) for v in spark.values],
        }

    stocks = [row(s) for s in t.sort_values("rank_score", ascending=False).index]
    by_sym = {r["sym"]: r for r in stocks}
    for r in stocks:
        if r["sym"] in t.index:
            by_sym[r["sym"]]["sell_reasons"] = reasons(pt.loc[r["sym"]], contrib.loc[r["sym"]], "sell")

    sectors = {}
    for sec, g in t.groupby("sector"):
        sectors[sec] = {
            "count": int(len(g)),
            "buy": list(g.sort_values("rank_score", ascending=False).index[:5]),
            "sell": list(g.sort_values("sell_score", ascending=False).index[:5]),
            "avg_buy": _r(g["buy"].mean(), 3), "avg_sell": _r(g["sell"].mean(), 3),
            "ret20": _r(W["sec_ret20"].iloc[-1][g.index].mean(), 4),
        }
    prev_top = tops[recent[-2]]
    summary_json = {
        "asof": str(today), "run": run_kind, "generated": pd.Timestamp.now(tz="Asia/Dhaka").strftime("%Y-%m-%d %H:%M"),
        "horizon_days": HORIZON, "buy_threshold": M.BUY_T, "sell_threshold": M.SELL_T,
        "mood": mood(ex["market"]),
        "top": top, "also": also,
        "new_entries": [s for s in top if s not in prev_top],
        "dropped": [s for s in prev_top if s not in top],
        "sell_top": M.top_list(t, cap=len(t), score="sell_score")[0],
        "sectors": sectors,
        "stocks": stocks,
        "types": {TYPE_LABEL[k]: int(v) for k, v in btype.loc[today].value_counts().items() if k in TYPE_LABEL},
        "stages": {STAGE_LABEL[k]: int(v) for k, v in stage.loc[today].value_counts().items()},
        "angles": list(ANGLES.keys()),
        "universe": int(len(t)),
    }
    _dump(summary_json, f"{out_dir}/summary.json")

    # track record
    track = {
        "summary": {k: (_r(v, 4) if isinstance(v, float) else v) for k, v in summary.items()},
        "weeks": [{"date": str(d), "top20": _r(r["top20"]), "market": _r(r["market"]), "all": _r(r["all_stocks"]),
                   "sell20": _r(r["sell20"]), "top_curve": _r(r["top20_curve"], 2),
                   "mkt_curve": _r(r["market_curve"], 2), "all_curve": _r(r["all_stocks_curve"], 2),
                   "sell_curve": _r(r["sell20_curve"], 2), "hit": _r(r["hit_rate"], 3),
                   "turnover": _r(r["turnover"], 2), "picks": r["picks"].split(",")}
                  for d, r in wk.iterrows()],
        "calibration": [{k: (_r(v, 4) if k != "bucket" else v) for k, v in rec.items()}
                        for rec in calib_table.to_dict("records")],
    }
    _dump(track, f"{out_dir}/track.json")

    # per-stock pages
    bands = ex["bands"]
    hist_prob = prob.copy()
    for sym in t.index:
        s_close = m.close[sym]
        valid = s_close.notna()
        idx = s_close.index[valid]
        piv = [{"date": str(dates[i]), "price": _r(pr, 3), "kind": k} for i, pr, k in ex["pivots"][sym]]
        hp = hist_prob.xs(sym, level="symbol")
        detail = {
            **by_sym[sym],
            "info": {k: (_r(info.at[sym, k], 3) if isinstance(info.at[sym, k], (float, np.floating, int)) else str(info.at[sym, k]))
                     for k in ["sector", "market_category", "paid_up_capital_mn", "market_cap_mn", "face_value",
                               "reserve_mn", "sponsor_pct", "govt_pct", "institute_pct", "foreign_pct", "public_pct"]},
            "contrib": {a: _r(contrib.at[sym, a], 2) for a in ANGLES},
            "metrics": {k: _r(pt.at[sym, k], 4) for k in
                        ["band60", "band120", "reward_risk", "up_room", "down_risk", "leg_progress", "ret5", "ret20",
                         "rsi", "vol_ratio5", "updown_vol", "trade_size", "vol20", "uc_hits20", "rel_mkt20",
                         "rel_sec20", "junk_score", "analog_ret", "analog_win", "regularity", "n_legs",
                         "up_len", "dn_len", "up_pct", "dn_pct", "exit_days", "med_trades", "history_days"]},
            "series": {
                "dates": [str(d) for d in idx],
                "close": [_r(v, 3) for v in s_close[valid]],
                "volume": [_r(v, 0) for v in m.volume[sym][valid]],
                "value": [_r(v, 3) for v in m.value[sym][valid]],
                "p10": [_r(v, 3) for v in bands["p10_60"][sym][valid]],
                "p90": [_r(v, 3) for v in bands["p90_60"][sym][valid]],
                "min120": [_r(v, 3) for v in bands["min120"][sym][valid]],
                "max120": [_r(v, 3) for v in bands["max120"][sym][valid]],
            },
            "pivots": piv,
            "scores": {"dates": [str(d) for d in hp.index], "buy": [_r(v, 3) for v in hp["buy"]],
                       "hold": [_r(v, 3) for v in hp["hold"]], "sell": [_r(v, 3) for v in hp["sell"]]},
            "analogs": [{"date": d, "ret": _r(r)} for d, r in ex["analogs"].get(sym, [])],
            "actions": [{"date": str(a.date), "pct": _r(a.est_pct, 1)} for a in m.actions[m.actions.symbol == sym].itertuples()],
        }
        _dump(detail, f"{out_dir}/stocks/{sym}.json")
    return t
