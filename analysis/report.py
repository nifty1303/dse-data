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


def mood_text(breadth, mkt20):
    """The market right now, in a few words."""
    from .expected import GLOOMY, HOT
    if pd.isna(breadth):
        return "the market mood is unknown"
    feel = "gloomy" if breadth < GLOOMY else "overheated" if breadth > HOT else "calm"
    return f"the market is {feel} ({breadth:.0%} of shares above their 20-day average; index {mkt20:+.1%} over the month)"


def journey(p, ph):
    """What the share is doing now (last month and this week), and against the market."""
    from .expected import PHASE_TEXT
    mv = float(np.clip((p["vol20"] if not pd.isna(p["vol20"]) else 0.02) * np.sqrt(20), 0.04, 0.15))
    s = (f"{ph}: {PHASE_TEXT.get(ph, '')}. Over the last month it moved {p['ret20']:+.1%} (it usually moves about ±{mv:.0%} in a month) "
         f"and {p['ret5']:+.1%} this week; it is " + ("at its 20-day high" if p["dd20"] > -0.005 else f"{-p['dd20']:.1%} below its 20-day high")
         + (" and at its 20-day low." if p["up20"] < 0.005 else f" and {p['up20']:.1%} above its 20-day low."))
    if not pd.isna(p["mkt_ret20"]):
        diff = p["ret20"] - p["mkt_ret20"]
        s += (f" It is doing {'better' if diff > 0 else 'worse'} than the market ({diff * 100:+.1f} points over the month), and "
              + mood_text(p["breadth"], p["mkt_ret20"]) + ".")
    return s


STOP_TEXT = {
    0: "just under its lowest close of the last 20 sessions (Tk {lvl:,.2f}), less half a normal day's move as a buffer",
    1: "just under its lowest close of the last 3 months (Tk {lvl:,.2f}), less half a normal day's move as a buffer",
    2: "its usual 2-week swing, because there is no support 3–12% below today's price that a stop could sit under",
}


TARGET_TEXT = {
    0: "the minimum goal of +5%: no resistance sits between +5% and what it usually moves in a month",
    1: "just under its 3-month high (Tk {lvl:,.2f}), where sellers stepped in last time",
    2: "just under its usual price level (Tk {lvl:,.2f}), where shares below it tend to drift back to",
    3: "just under the top of its 2-year regular range (Tk {lvl:,.2f})",
}


def fair_name(shift):
    return "1-year average (it moved to a new price range in the last year)" if shift else "2-year average"


def dev_text(dv, avg, shift=False):
    return (f"{dv:+.1%} vs its usual price level, the {fair_name(shift)} (Tk {avg:,.2f}): "
            + ("well above its usual level, so more room to fall back." if dv > 0.20 else
               "above its usual level." if dv > 0.03 else
               "close to its usual level." if dv >= -0.03 else
               "below its usual level, cheap by its own history." if dv >= -0.15 else
               "well below its usual level, cheap by its own history (but it may be cheap for a reason)."))


def tag_reason(r, price, sell_by, basis, tbasis):
    """Rule checks behind the tag, a one-line verdict and the plan's rationale."""
    from .expected import BUY_LEAD, DRASTIC_RET5, DRASTIC_RSI, GLOOMY, HOT, JUNK_LEAD, NO_BUY_PHASES, SELL_DEV
    pt, ps, sd, td = float(r["hit"]), float(r["stop_p"]), float(r["stop_dist"]), float(r["target_dist"])
    dv = float(r["dev2y"]) if not pd.isna(r["dev2y"]) else 0.0
    up, dn = price * (1 + td), price * (1 - sd)
    lead, junk, ph = pt - ps, bool(r["junk"]), r["phase"]
    need = JUNK_LEAD if junk else BUY_LEAD
    drastic, falling, signs = bool(r["drastic"]), bool(r["falling"]), str(r["turn_signs"] or "")
    br, m20, r20 = float(r["breadth"]), float(r["mkt_ret20"]), float(r["ret20"])
    mkt_ok, extreme = bool(r["mkt_ok"]), not pd.isna(br) and (br < GLOOMY or br > HOT)
    hard = [s for s, on in [(f"{float(r['ret5']):+.0%} this week", float(r["ret5"]) < DRASTIC_RET5),
                            (f"{int(r['lc_hits20'])} limit-down day(s) in 4 weeks", r["lc_hits20"] > 0),
                            (f"RSI {float(r['rsi']):.0f}", float(r["rsi"]) < DRASTIC_RSI)] if on]
    buy = [{"ok": bool(lead >= need),
            "text": f"Take-profit first (Tk {up:,.2f}, +{td:.1%}) {pt:.0%} vs stop first (Tk {dn:,.2f}, −{sd:.1%}) {ps:.0%}: "
                    f"lead {lead * 100:+.0f} points (needs {need * 100:+.0f}" + (", higher for operator / junk shares" if junk else "") + ")"},
           {"ok": bool(dv < 0), "text": f"Price is below its usual level ({dv:+.1%})"},
           {"ok": bool(ph not in NO_BUY_PHASES), "text": f"Journey is not Turning down (it is {ph})"},
           {"ok": not drastic, "text": "Not in a drastic fall (10%+ down in a week, a limit-down day in 4 weeks, or RSI below 35)"
                                       + (f": {', '.join(hard)}" if hard else "")},
           {"ok": bool(not falling or signs), "text": "If falling, it shows a turn: a higher 10-day low, 5-day average above 10-day, or 3%+ off its 10-day low"
                                                      + (f" (seen: {signs})" if falling and signs else " (none yet)" if falling else " (not falling)")},
           {"ok": mkt_ok, "text": "If the market is gloomy or overheated (under 30% or over 70% of shares above their 20-day average), "
                                  f"the share is doing better than the market: now {mood_text(br, m20)}"
                                  + (f"; the share moved {r20:+.1%} over the month" if extreme else "")}]
    sell = [{"ok": bool(ps > pt and dv >= 0),
             "text": f"Stop first is more likely than take-profit first ({ps:.0%} vs {pt:.0%}) while the price is at or above its usual level ({dv:+.1%})"},
            {"ok": bool(dv > SELL_DEV and lead < BUY_LEAD),
             "text": f"Price is more than {SELL_DEV:.0%} above its usual level ({dv:+.1%}) without a {BUY_LEAD * 100:+.0f} lead ({lead * 100:+.0f})"}]
    if r["verdict"] == "Sell":
        why = ("Sell: " + (f"it is more likely to fall to its stop (Tk {dn:,.2f}, −{sd:.1%}) than reach its take-profit (Tk {up:,.2f}) first "
                           f"by {sell_by} ({ps:.0%} vs {pt:.0%}), and at {dv:+.1%} vs its usual price level it isn't cheap enough to wait for a bounce."
                           if ps > pt and dv >= 0 else
                           f"it is {dv:+.0%} above its usual price level and the odds don't support more upside (lead {lead * 100:+.0f}); "
                           "shares this stretched have tended to fall back."))
    elif r["verdict"] == "Buy":
        why = (f"Buy: {pt:.0%} chance of reaching its take-profit Tk {up:,.2f} (+{td:.1%}) before {sell_by} against {ps:.0%} of first falling to "
               f"its stop Tk {dn:,.2f} (−{sd:.1%}), a lead of {lead * 100:.0f} points; it is {-dv:.1%} below its usual price level, and the journey "
               f"({ph}) allows a Buy" + (f"; it has been falling but shows a turn ({signs})." if falling else "."))
    else:
        miss = []
        if lead < need:
            miss.append(f"its lead of {lead * 100:+.0f} points is below {need * 100:+.0f}")
        if dv >= 0:
            miss.append(f"it is {dv:+.1%} vs its usual price level, so not cheap")
        if ph in NO_BUY_PHASES:
            miss.append("it is turning down: it has given back much of its recent rise, wait for it to settle")
        if drastic:
            miss.append(f"it is falling hard ({', '.join(hard)}): wait for the selling to calm down")
        elif falling and not signs:
            miss.append("it is still falling with no sign of a turn yet: wait for a higher low or a bounce off the bottom")
        if not mkt_ok:
            miss.append(f"{mood_text(br, m20)}, and this share ({r20:+.1%} over the month) is not doing better than the market")
        why = "Neutral: " + ("; ".join(miss) + "." if miss else "no clear edge.")
    rr = td / sd
    be = sd / (td + sd)
    rat = [f"Odds by {sell_by}: take-profit first {pt:.0%}, stop first {ps:.0%}, neither {max(0.0, 1 - pt - ps):.0%}.",
           f"Take-profit Tk {up:,.2f} (+{td:.1%}): " + tbasis + ".",
           f"Stop-loss Tk {dn:,.2f} (−{sd:.1%}): " + basis + ".",
           f"Reward : risk is {rr:.1f} : 1; before costs you break even if the take-profit comes first in more than {be:.0%} "
           f"of the decided trades, and this share's odds give {pt / max(pt + ps, 1e-9):.0%}."]
    return buy, sell, why, rat


def change_text(r, y):
    """What changed in the plan since the previous session."""
    if y is None:
        return ["New in the analysis today."]
    out = []
    if y["verdict"] != r["verdict"]:
        out.append(f"Tag changed {y['verdict']} → {r['verdict']}.")
    if abs(r["hit"] - y["hit"]) >= 0.02 or abs(r["stop_p"] - y["stop_p"]) >= 0.02:
        out.append(f"Take-profit-first chance {y['hit']:.0%} → {r['hit']:.0%}, stop-first {y['stop_p']:.0%} → {r['stop_p']:.0%}.")
    if abs(r["target_dist"] - y["target_dist"]) >= 0.005:
        out.append(f"Take-profit {y['target_dist']:+.1%} → {r['target_dist']:+.1%}.")
    if abs(r["stop_dist"] - y["stop_dist"]) >= 0.005:
        out.append(f"Stop distance {y['stop_dist']:.1%} → {r['stop_dist']:.1%}.")
    return out or ["No meaningful change since the previous session."]


def trade_plan(p, price, r, liq, days, sell_by, basis, tbasis):
    """1-month plan: buy zone, the share's own take-profit and stop, sell-by date."""
    sd = float(np.clip(p["vol20"] if not pd.isna(p["vol20"]) else 0.02, 0.005, 0.08))
    dist, td = float(r["stop_dist"]), float(r["target_dist"])
    stop, tp = price * (1 - dist), price * (1 + td)
    entry_hi = price * (1 + min(0.5 * sd, 0.01))
    entry_lo = max(stop * 1.03, price * (1 - sd))
    rr = td / max(dist, 1e-9)
    return {"entry_lo": _r(entry_lo, 2), "entry_hi": _r(entry_hi, 2), "stop": _r(stop, 2), "stop_basis": basis,
            "take_profit": _r(tp, 2), "tp_basis": tbasis, "rr": _r(rr, 2), "risk_pct": _r(dist, 4),
            "reward_pct": _r(td, 4), "liq": _r(liq, 2), "sell_by": sell_by,
            "rr_label": "Good" if rr >= 1.2 else "Fair" if rr >= 0.7 else "Wide stop", "hold_days": days}


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

    h_extra = next(iter(H.values()))["extra"]
    dev2 = pt["dev2y"]                    # price vs its usual level (bonus-adjusted)
    shares = info.index[info["is_equity"] & ~info["is_fund"]]

    def horizon_row(key, sym):
        t, yday = per[key]["t"], per[key]["tables"][recent[-2]]
        r = t.loc[sym]
        why, caution = reasons(pt.loc[sym], per[key]["contrib"].loc[sym], ctx(sym), key)
        goal, sell_by = h_extra["goal"], pd.Timestamp(h_extra["sell_by"]).strftime("%d %b %Y").lstrip("0")
        price = float(close_raw[sym])
        code = int(pt.at[sym, "stop_basis"]) if not pd.isna(pt.at[sym, "stop_basis"]) else 2
        vd = float(np.clip(pt.at[sym, "vol20"] if not pd.isna(pt.at[sym, "vol20"]) else 0.02, 0.005, 0.08))
        basis = STOP_TEXT[code].format(lvl=price * (1 - float(r["stop_dist"])) / (1 - 0.5 * vd))
        tcode = int(pt.at[sym, "target_basis"]) if not pd.isna(pt.at[sym, "target_basis"]) else 0
        tbasis = TARGET_TEXT[tcode].format(lvl=price * (1 + float(r["target_dist"])) / 0.99)
        rule_buy, rule_sell, tag_why, rationale = tag_reason(r, price, sell_by, basis, tbasis)
        rationale.append(journey(pt.loc[sym], r["phase"]))
        dv = float(dev2[sym]) if not pd.isna(dev2[sym]) else None
        if dv is not None:
            rationale.append("Price " + dev_text(dv, price / (1 + dv), bool(pt.at[sym, "fair_shift"] == 1)))
        changes = change_text(r, yday.loc[sym] if sym in yday.index else None)
        since, n_days = today, 0
        for d in reversed(recent):
            tb = per[key]["tables"][d]
            if sym in tb.index and tb.at[sym, "verdict"] == r["verdict"]:
                since, n_days = d, n_days + 1
            else:
                break
        liq = math.expm1(pt.at[sym, "liq_value"]) if not pd.isna(pt.at[sym, "liq_value"]) else 0.0
        plan = trade_plan(pt.loc[sym], price, r, liq, HORIZONS[key]["days"], sell_by, basis, tbasis)
        rationale.append(f"It trades about Tk {liq:,.1f} mn a day, so " + ("getting in and out is easy." if liq >= 5 else
                         "keep the position modest: exits can be slow." if liq >= 0.5 else
                         "it is thinly traded: a stop-loss may fill well below its level."))
        return {"buy": _r(r["buy"], 3), "sell": _r(r["sell"], 3), "move": _r(r["move"], 3),
                "dir": _r(r["direction"], 3), "exp": _r(r["exp"], 4) if "exp" in t else None,
                "hit": _r(r["hit"], 3), "stop_p": _r(r["stop_p"], 3), "lead": _r(r["lead"], 3),
                "stop_dist": _r(r["stop_dist"], 4), "target_dist": _r(r["target_dist"], 4), "rationale": rationale, "changes": changes,
                "phase": r["phase"], "journey": journey(pt.loc[sym], r["phase"]),
                "target": _r(close_raw[sym] * (1 + r["exp"]), 2),
                "path_lo": _r(close_raw[sym] * (1 + r["path_lo"]), 2) if "path_lo" in t else None,
                "path_hi": _r(close_raw[sym] * (1 + r["path_hi"]), 2) if "path_hi" in t else None,
                "conf": int(r["conf"]), "verdict": r["verdict"],
                "score": _r(r["rank_score"], 5), "sscore": _r(r["sell_score"], 5),
                "rank": int(r["rank"]), "srank": int(per[key]["srank"][sym]),
                "rank_prev": int(yday.at[sym, "rank"]) if sym in yday.index else None,
                "days_top": days_in_top(key, sym), "why": why, "caution": caution,
                "tag_why": tag_why, "rule_buy": rule_buy, "rule_sell": rule_sell,
                "tag_since": str(since), "tag_days": n_days, "plan": plan}

    stocks = []
    for sym in per["short"]["t"].index:
        p = pt.loc[sym]
        typ = p["up_len"] if p["leg_dir"] == 1 else p["dn_len"]
        stocks.append({
            "sym": sym, "sector": info.at[sym, "sector"], "cat": info.at[sym, "market_category"],
            "type": TYPE_LABEL.get(btype.at[today, sym], "Mixed"), "stage": STAGE_LABEL.get(stage.at[today, sym], "Quiet"),
            "close": _r(close_raw[sym], 2), "chg": _r(close_raw[sym] / prev_raw[sym] - 1, 4),
            "dev2y": _r(dev2[sym], 4), "fair_basis": "1-year" if pt.at[sym, "fair_shift"] == 1 else "2-year", "avg2y": _r(close_raw[sym] / (1 + dev2[sym]), 2) if not pd.isna(dev2[sym]) else None,
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
                            "avg_exp": _r(g["lead"].mean(), 3),
                            "ret20": _r(W["sec_ret20"].iloc[-1][g.index].mean(), 4)}
        horizons[key] = {
            "label": hz["label"], "long_label": hz["long_label"], "days": hz["days"], "thr": hz["thr"],
            "top": top, "also": also, "sell_top": M.top_list(t, cap=len(t), score="sell_score")[0],
            "new_entries": [s for s in top if s not in prev_top], "dropped": [s for s in prev_top if s not in top],
            "sectors": sectors, "verdicts": {k: int(v) for k, v in t["verdict"].value_counts().items()},
            "phases": {k: int(v) for k, v in t["phase"].value_counts().items()},
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
                         "exp": [_r(tb[d].at[sym, "lead"], 3) for d in ds],
                         "verdict": [tb[d].at[sym, "verdict"] for d in ds],
                         "phase": [tb[d].at[sym, "phase"] for d in ds]}
        detail = {
            **by_sym[sym],
            "info": {k: (info.at[sym, k] if isinstance(info.at[sym, k], str) else _r(info.at[sym, k], 3))
                     for k in ["sector", "market_category", "paid_up_capital_mn", "market_cap_mn", "face_value",
                               "reserve_mn", "sponsor_pct", "govt_pct", "institute_pct", "foreign_pct", "public_pct"]},
            "contrib": {key: {a: _r(per[key]["contrib"].at[sym, a], 2) for a in MODEL_ANGLES} for key in H},
            "levels": {k: _r(bands[k][sym].iloc[-1], 3) for k in bands},
            "metrics": {k: _r(pt.at[sym, k], 4) for k in
                        ["band_all", "band60", "reward_risk", "up_room", "down_risk", "leg_progress", "ret5", "ret20",
                         "rsi", "vol_ratio5", "updown_vol", "trade_size", "vol20", "reach20", "reach5_hits20", "uc_hits20", "rel_mkt20",
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
