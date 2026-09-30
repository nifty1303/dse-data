"""Turn scores into the JSON files the website reads."""

import json
import math
import os

import numpy as np
import pandas as pd

from . import model as M
from .features import HORIZONS, MODEL_ANGLES

TYPE_LABEL = {"cycler": "Steady cycler", "trender": "Trender", "junk": "Operator / junk",
              "dead": "Dead / illiquid", "mixed": "Mixed", "new": "New listing"}
STAGE_LABEL = {"quiet": "Quiet", "accumulation": "Accumulation", "markup": "Markup",
               "distribution": "Distribution", "dump": "Dump"}


def _r(x, n=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else round(x, n)


def _dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), allow_nan=False)


def tk(x):
    return "–" if x is None or pd.isna(x) else f"Tk {x:,.2f}" if x < 100 else f"Tk {x:,.1f}"


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


# ------------------------------------------------------------ market mood
def mood(market):
    last = market.iloc[-1]
    score = float(last["mood"])
    label = ("Friendly" if score > 0.3 else "Neutral" if score > 0
             else "Caution" if score > -0.3 else "Hostile")
    r20, ad, tt = last["mkt_ret20"], last["adv_dec5"], last["turnover_trend"]
    reasons = [
        f"The market index is {'up' if r20 >= 0 else 'down'} {abs(r20):.1%} over the last 4 weeks.",
        f"{last['breadth']:.0%} of shares are trading above their 20-day average (market breadth).",
        f"Over the last 5 days there were {'more risers than fallers' if ad > 0 else 'more fallers than risers'} "
        f"(net {ad:+.0%}).",
        f"Daily turnover is {abs(math.exp(tt) - 1):.0%} {'above' if tt > 0 else 'below'} its 6-month norm.",
        f"{last['near_low']:.0%} of shares sit in the bottom fifth of their 3-month range; "
        f"{last['near_high']:.0%} sit in the top fifth.",
    ]
    warning = None
    if label in ("Caution", "Hostile"):
        warning = ("The overall market is weak. Buy signals fail more often in a falling "
                   "market, so consider smaller positions or waiting for the mood to improve.")
    hist = market.tail(250)
    return {"label": label, "score": _r(score, 3), "reasons": reasons, "warning": warning,
            "history": {"dates": [str(d) for d in hist.index], "mood": [_r(v, 3) for v in hist["mood"]]}}


# ------------------------------------------------------------ reasons in full sentences
def tone(angle, p, key):
    """+1 if the fact itself reads as good for a buyer, -1 if bad, 0 if neutral."""
    sgn = lambda x, band: 0 if pd.isna(x) or abs(x) < band else (1 if x > 0 else -1)
    if angle == "Cycle position":
        b = p["band_all"]
        return 0 if pd.isna(b) else 1 if b < 0.25 else -1 if b > 0.75 else 0
    if angle == "Trend & momentum":
        return 1 if p["rsi"] < 30 else -1 if p["rsi"] > 70 else sgn(p["ret20"], 0.02)
    if angle == "Money flow":
        return sgn(p["updown_vol"], 0.1)
    if angle == "Liquidity":
        return 1 if not pd.isna(p["liq_value"]) and math.expm1(p["liq_value"]) >= 1 else -1
    if angle == "Risk":
        if p["vol20"] > 0.035 or p["uc_hits20"] > 0 or p["drawdown120"] < -0.2:
            return -1
        return 1 if p["vol20"] < 0.015 else 0
    if angle == "Relative strength":
        return sgn(p["rel_mkt20"], 0.01)
    if angle == "Fundamentals":
        return -1 if (p["cat_Z"] or p["reserve_neg"]) else 1 if p["cat_A"] else 0
    if angle == "Junk pattern":
        if p["junk_score"] >= 0.62 or p["stage_dump"] or p["stage_distribution"] or p["stage_markup"]:
            return -1
        return 1 if (p["junk_score"] < 0.4 or p["stage_accumulation"]) else 0
    if angle == "Similar setups":
        return sgn(p[f"analog_ret_{key}"], 0.01)
    return 0


def sentence(angle, p, ctx, key):
    """One or two plain-English sentences, with the numbers, for one angle."""
    hz = HORIZONS[key]
    if angle == "Cycle position":
        b = p["band_all"]
        s = (f"At {tk(ctx['price'])}, the share sits {pct(b)} of the way up its regular 2-year range "
             f"({tk(ctx['lo'])}–{tk(ctx['hi'])}, the 10th–90th percentile)")
        if pd.isna(b):
            s = "There isn't enough history yet to place it in a 2-year range"
        elif b < 0:
            s += " — below its usual floor, a zone where it has tended to bounce."
        elif b < 0.25:
            s += " — near the bottom, where it has often bounced before."
        elif b > 1:
            s += " — above its usual ceiling, where rallies have tended to stall."
        elif b > 0.75:
            s += " — near the top, where it has often stalled."
        else:
            s += "."
        if p["leg_dir"] and not pd.isna(p["leg_days"]):
            up = p["leg_dir"] == 1
            typ = p["up_len"] if up else p["dn_len"]
            s += f" In the current swing it has been {'rising' if up else 'falling'} for {int(p['leg_days'])} trading days"
            if not pd.isna(typ):
                s += (f", longer than its usual {int(typ)}-day {'rise' if up else 'fall'}." if p["leg_days"] > 1.5 * typ
                      else f"; a typical {'rise' if up else 'fall'} lasts about {int(typ)} days.")
            else:
                s += "."
        return s
    if angle == "Trend & momentum":
        rsi = p["rsi"]
        zone = "oversold" if rsi < 30 else "overbought" if rsi > 70 else "neutral"
        return (f"It is {'up' if p['ret5'] >= 0 else 'down'} {abs(p['ret5']):.1%} this week and "
                f"{'up' if p['ret20'] >= 0 else 'down'} {abs(p['ret20']):.1%} over 4 weeks, trading {abs(p['dist_ma20']):.1%} {'above' if p['dist_ma20'] >= 0 else 'below'} "
                f"its 20-day average; RSI(14) is {rsi:.0f} ({zone}).")
    if angle == "Money flow":
        vr = math.exp(p["vol_ratio5"]) if not pd.isna(p["vol_ratio5"]) else 1
        ud = math.exp(p["updown_vol"]) if not pd.isna(p["updown_vol"]) else 1
        side = ("buyers are in control (accumulation)" if ud > 1.1 else
                "sellers are in control (distribution)" if ud < 0.9 else "buyers and sellers are evenly matched")
        return (f"This week's volume is {vr:.1f}× its normal level, and over 4 weeks {ud:.1f}× as many shares "
                f"traded on up days as on down days — {side}.")
    if angle == "Liquidity":
        liq = math.expm1(p["liq_value"]) if not pd.isna(p["liq_value"]) else 0
        ease = ("buying and selling is easy" if liq >= 5 else "it is reasonably tradable" if liq >= 1
                else "it can be hard to get in and out without moving the price")
        return f"It trades about Tk {liq:.1f} million a day (about {p['med_trades']:.0f} trades), so {ease}."
    if angle == "Risk":
        v = p["vol20"]
        s = f"Its price moves about {v:.1%} a day on average"
        s += ", which is calm" if v < 0.015 else ", which is volatile" if v > 0.035 else ""
        if p["uc_hits20"] > 0:
            s += f"; it hit the upper circuit limit {int(p['uc_hits20'])} time(s) in the last 4 weeks"
        if p["drawdown120"] < -0.15:
            s += f"; it is {abs(p['drawdown120']):.0%} below its 6-month high"
        return s + "."
    if angle == "Relative strength":
        rm, rs = p["rel_mkt20"], p["rel_sec20"]
        return (f"Over the last 4 weeks it has {'beaten' if rm >= 0 else 'lagged'} the market by {abs(rm):.1%} and "
                f"{'beaten' if rs >= 0 else 'lagged'} its own sector by {abs(rs):.1%} (relative strength).")
    if angle == "Fundamentals":
        cat = "A" if p["cat_A"] else "B" if p["cat_B"] else "Z" if p["cat_Z"] else "N"
        s = f"It is a Category {cat} company; sponsors and directors hold {p['sponsor_pct']:.0%}"
        if p["institute_pct"] > 0.05:
            s += f" and institutions {p['institute_pct']:.0%}"
        s += "; its reserves are negative, a sign of weak finances." if p["reserve_neg"] else "."
        if not pd.isna(p["px_face"]) and p["px_face"] < 0:
            s += " It trades below its face value."
        return s
    if angle == "Junk pattern":
        j = p["junk_score"]
        s = (f"Its junk-pattern score is {j:.0%} — "
             + ("it trades like a normal share." if j < 0.4 else
                "it behaves like an operator-driven share (spikes, circuit runs, small float)." if j >= 0.62
                else "it shows some operator-style traits."))
        stage = next((k for k in ["markup", "distribution", "dump", "accumulation"] if p[f"stage_{k}"]), None)
        s += {
            "markup": " It looks to be in a markup phase: a sharp rise on heavy volume that can reverse quickly.",
            "distribution": " It looks to be in a distribution phase: heavy volume while the price stalls, often insiders selling.",
            "dump": " It looks to be in a dump phase: falling hard after a pump.",
            "accumulation": " It looks to be in an accumulation phase: quiet buying at flat prices, which can come before a rise.",
        }.get(stage, "")
        return s
    if angle == "Similar setups":
        ar, aw = p[f"analog_ret_{key}"], p[f"analog_win_{key}"]
        if pd.isna(ar):
            return "There aren't enough similar past setups in this share yet to compare."
        return (f"The 7 most similar past setups in this share went on to {'gain' if ar >= 0 else 'lose'} "
                f"{abs(ar):.1%} on average over the following {hz['after']}, and {aw:.0%} of them rose.")
    return angle


def reasons(p, contrib_row, ctx, key, n=3):
    """
    Reasons to buy: angles that lift the score AND whose facts read as good news.
    Cautions: angles that lower it AND read as bad news. The model weighs angles in
    combination, so a fact can nudge the score the "wrong" way; those are left out
    rather than shown as a contradictory reason.
    """
    t = {a: tone(a, p, key) for a in contrib_row.index}
    pos = [a for a in contrib_row[contrib_row > 0.3].sort_values(ascending=False).index if t[a] >= 0]
    neg = [a for a in contrib_row[contrib_row < -0.3].sort_values().index if t[a] <= 0]
    pos = sorted(pos, key=lambda a: -t[a])[:n]          # clear good news first
    neg = sorted(neg, key=lambda a: t[a])[:n]
    return [sentence(a, p, ctx, key) for a in pos], [sentence(a, p, ctx, key) for a in neg]


# ------------------------------------------------------------ main builder
def build(m, panel, ex, H, market_mood, out_dir, run_kind):
    """H: {key: {"score_days": rows -> {date: table}, "contrib": panel day -> DataFrame,
                 "wk", "calib", "summary", "extra"}}."""
    dates = m.dates
    today = dates[-1]
    recent = dates[-60:]
    info, btype, stage, W = m.info, ex["btype"], ex["stage"], ex["wide"]
    bands = ex["bands"]
    pt = panel.xs(today, level="date")
    rows = panel.loc[panel.index.get_level_values("date") >= dates[-62]]   # 2 extra days warm the 3-day smoothing
    close_raw, prev_raw = m.raw_close.iloc[-1], m.raw_close.iloc[-2]

    per = {}
    for key, h in H.items():
        tables = h["score_days"](rows)
        tops = {d: M.top_list(tables[d])[0] for d in recent}
        per[key] = {"tables": tables, "tops": tops, "t": tables[today], "contrib": h["contrib"](pt)}

    for key in per:
        per[key]["srank"] = per[key]["t"]["sell_score"].rank(ascending=False, method="first").astype(int)

    def days_in_top(key, sym):
        n = 0
        for d in reversed(recent):
            if sym in per[key]["tops"][d]:
                n += 1
            else:
                break
        return n

    def ctx(sym):
        return {"price": close_raw[sym], "lo": bands["p10_all"][sym].iloc[-1], "hi": bands["p90_all"][sym].iloc[-1]}

    def horizon_row(key, sym):
        t, yday = per[key]["t"], per[key]["tables"][recent[-2]]
        r = t.loc[sym]
        why, caution = reasons(pt.loc[sym], per[key]["contrib"].loc[sym], ctx(sym), key)
        return {"buy": _r(r["buy"], 3), "sell": _r(r["sell"], 3), "move": _r(r["move"], 3),
                "dir": _r(r["direction"], 3), "exp": _r(r["exp"], 4) if "exp" in t else None,
                **({"outlook": _r(r["outlook"], 4), "tilt": _r(r["tilt"], 4), "season": _r(r["season"], 4),
                    "weekday": _r(r["weekday_adj"], 4), "verdict_pre": r["verdict_pre"]} if "exp" in t else {}),
                "conf": int(r["conf"]), "verdict": r["verdict"],
                "score": _r(r["rank_score"], 5), "sscore": _r(r["sell_score"], 5),
                "rank": int(r["rank"]), "srank": int(per[key]["srank"][sym]),
                "rank_prev": int(yday.at[sym, "rank"]) if sym in yday.index else None,
                "days_top": days_in_top(key, sym), "why": why, "caution": caution}

    stocks = []
    for sym in per["short"]["t"].index:
        p = pt.loc[sym]
        typ = p["up_len"] if p["leg_dir"] == 1 else p["dn_len"]
        stocks.append({
            "sym": sym, "sector": info.at[sym, "sector"], "cat": info.at[sym, "market_category"],
            "type": TYPE_LABEL.get(btype.at[today, sym], "Mixed"), "stage": STAGE_LABEL.get(stage.at[today, sym], "Quiet"),
            "close": _r(close_raw[sym], 2), "chg": _r(close_raw[sym] / prev_raw[sym] - 1, 4),
            "band": _r(p["band_all"], 3), "swing": _r(p["band60"], 3),
            "up_room": _r(p["up_room"], 3), "down_risk": _r(p["down_risk"], 3),
            "leg": int(p["leg_dir"]) if not pd.isna(p["leg_dir"]) else 0,
            "leg_days": _r(p["leg_days"], 0), "leg_typ": _r(typ, 0),
            "liq": _r(math.expm1(p["liq_value"]), 2) if not pd.isna(p["liq_value"]) else None,
            "junk": _r(p["junk_score"], 2),
            "spark": [_r(v, 2) for v in m.close[sym].iloc[-40:].values],
            "s": horizon_row("short", sym),
        })
    by_sym = {r["sym"]: r for r in stocks}

    horizons = {}
    for key, h in H.items():
        hz, t = HORIZONS[key], per[key]["t"]
        top, also = M.top_list(t)
        prev_top = per[key]["tops"][recent[-2]]
        sectors = {}
        for sec, g in t.groupby("sector"):
            sectors[sec] = {"count": int(len(g)),
                            "buy": list(g.sort_values("rank_score", ascending=False).index[:5]),
                            "sell": list(g.sort_values("sell_score", ascending=False).index[:5]),
                            "avg_dir": _r(g["direction"].mean(), 3),
                            "avg_exp": _r(g["exp"].mean(), 4) if "exp" in g else None,
                            "ret20": _r(W["sec_ret20"].iloc[-1][g.index].mean(), 4)}
        horizons[key] = {
            "label": hz["label"], "long_label": hz["long_label"], "days": hz["days"], "thr": hz["thr"],
            "top": top, "also": also, "sell_top": M.top_list(t, cap=len(t), score="sell_score")[0],
            "new_entries": [s for s in top if s not in prev_top], "dropped": [s for s in prev_top if s not in top],
            "sectors": sectors, "verdicts": {k: int(v) for k, v in t["verdict"].value_counts().items()},
            **h["extra"],
        }
    _dump({
        "asof": str(today), "run": run_kind,
        "generated": pd.Timestamp.now(tz="Asia/Dhaka").strftime("%Y-%m-%d %H:%M"),
        "mood": market_mood, "horizons": horizons, "stocks": stocks,
        "types": {TYPE_LABEL[k]: int(v) for k, v in btype.loc[today].value_counts().items() if k in TYPE_LABEL},
        "universe": len(stocks),
    }, f"{out_dir}/summary.json")

    # track record
    track = {}
    for key, h in H.items():
        wk = h["wk"]
        curve = {c: [_r(v, 2) for v in wk[f"{c}_curve"]] for c in ["top20", "market", "all_stocks", "sell20"]} \
            if h["summary"]["compounding"] else None
        track[key] = {
            "summary": {k: (_r(v, 4) if isinstance(v, float) else v) for k, v in h["summary"].items()},
            "periods": [{"date": str(d), "top20": _r(r["top20"]), "market": _r(r["market"]), "all": _r(r["all_stocks"]),
                         "sell20": _r(r["sell20"]), "hit": _r(r["hit_rate"], 3), "target": _r(r["target_rate"], 3),
                         "picks": r["picks"].split(",")} for d, r in wk.iterrows()],
            "curve": curve,
            "calibration": [{k: (v if k == "bucket" else _r(v, 4)) for k, v in rec.items()}
                            for rec in h["calib"].to_dict("records")],
            "extra": h["extra"],
        }
    _dump(track, f"{out_dir}/track.json")

    # per-stock pages
    for sym in per["short"]["t"].index:
        s_close = m.close[sym]
        valid = s_close.notna()
        idx = s_close.index[valid]
        ser = lambda df: [_r(v, 3) for v in df[sym][valid]]
        hist = {}
        for key in H:
            tb = per[key]["tables"]
            ds = [d for d in recent if sym in tb[d].index]
            hist[key] = {"dates": [str(d) for d in ds], "dir": [_r(tb[d].at[sym, "direction"], 3) for d in ds],
                         "move": [_r(tb[d].at[sym, "move"], 3) for d in ds],
                         "exp": [_r(tb[d].at[sym, "exp"], 4) for d in ds] if "exp" in tb[recent[-1]] else None}
        detail = {
            **by_sym[sym],
            "info": {k: (info.at[sym, k] if isinstance(info.at[sym, k], str) else _r(info.at[sym, k], 3))
                     for k in ["sector", "market_category", "paid_up_capital_mn", "market_cap_mn", "face_value",
                               "reserve_mn", "sponsor_pct", "govt_pct", "institute_pct", "foreign_pct", "public_pct"]},
            "contrib": {key: {a: _r(per[key]["contrib"].at[sym, a], 2) for a in MODEL_ANGLES} for key in H},
            "levels": {k: _r(bands[k][sym].iloc[-1], 3) for k in bands},
            "metrics": {k: _r(pt.at[sym, k], 4) for k in
                        ["band_all", "band60", "reward_risk", "up_room", "down_risk", "leg_progress", "ret5", "ret20",
                         "rsi", "vol_ratio5", "updown_vol", "trade_size", "vol20", "uc_hits20", "rel_mkt20",
                         "rel_sec20", "junk_score", "analog_ret_short", "analog_win_short", "regularity", "n_legs", "up_len", "dn_len", "up_pct", "dn_pct",
                         "med_trades", "history_days"]},
            "series": {"dates": [str(d) for d in idx], "close": ser(m.close), "volume": [_r(v, 0) for v in m.volume[sym][valid]],
                       **{k: ser(bands[k]) for k in bands}},
            "pivots": [{"date": str(dates[i]), "price": _r(pr, 3), "kind": k} for i, pr, k in ex["pivots"][sym]],
            "history": hist,
            "analogs": {key: [{"date": d, "ret": _r(r)} for d, r in ex["analogs"][key].get(sym, [])] for key in H},
            "actions": [{"date": str(a.date), "pct": _r(a.est_pct, 1)} for a in m.actions[m.actions.symbol == sym].itertuples()],
        }
        _dump(detail, f"{out_dir}/stocks/{sym}.json")
    return {key: per[key]["t"] for key in H}
