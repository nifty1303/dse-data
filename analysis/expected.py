"""
Expected 2-week move, the share's journey, and the verdict.

Expected move = calibrated chance of a >3% rise x the average such rise + chance of
a >3% fall x the average such fall + the rest x the average small move.

Verdict: the direction comes from the expected move (up = Buy, down = Sell); the
strength comes from the journey (where the share is on its current swing). Tested
on unseen data, see analyze.py.

Calendar effects (month, weekday) and a 2-year-cycle tilt were also tested as
add-ons to the expected move; none improved it, so they are shown for reference only.
"""

import numpy as np
import pandas as pd

CLIP = (-0.40, 0.60)          # keep one-off pumps from dominating averages
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]


def outcome_averages(fwd_wide, universe, thr):
    """Average return over the period when a share rose past thr, fell past -thr, or neither."""
    f = fwd_wide[universe].clip(*CLIP).stack()
    return {"up": float(f[f > thr].mean()), "down": float(f[f < -thr].mean()),
            "flat": float(f[(f >= -thr) & (f <= thr)].mean())}


def outlook(odds, avg):
    """Expected move implied by calibrated buy/sell odds."""
    flat = (1 - odds["buy"] - odds["sell"]).clip(lower=0)
    return odds["buy"] * avg["up"] + odds["sell"] * avg["down"] + flat * avg["flat"]


# ------------------------------------------------------------ calendar effects
def season_month(date, days):
    """Month a period mostly falls in (its midpoint): a 2-week buy on 30 Sep is an October trade."""
    return (pd.Timestamp(date) + pd.Timedelta(days=int(days * 0.7))).strftime("%m")


def weekday(date):
    return pd.Timestamp(date).day_name()


def market_path(fwd_wide, universe):
    """Return of the average share over the period starting each day (clipped)."""
    return fwd_wide[universe].clip(*CLIP).mean(axis=1).dropna()


def calendar_tables(mk, days):
    """Average period return of the average share by month (period midpoint) and by weekday bought."""
    return {"base": float(mk.mean()),
            "month_raw": mk.groupby([season_month(d, days) for d in mk.index]).mean().to_dict(),
            "weekday_raw": mk.groupby([weekday(d) for d in mk.index]).mean().to_dict()}


def thursday_stats(close, universe, dates, recent=62):
    """Weekday effects for the timing tip: the average share's move by weekday, over 2 years and the
    last `recent` sessions (~3 months), and whether the tip applies to the next session.

    The tip ("buying at Thursday's close? Sunday has tended to be cheaper") is shown only when the next
    session is a Thursday and Sundays are still weak lately (both over 3 and 6 months)."""
    r = close[universe].pct_change(fill_method=None).clip(-0.2, 0.2).mean(axis=1).dropna()
    wd = pd.Series([weekday(d) for d in r.index], index=r.index)
    nxt = r.shift(-1)                                  # next session's move after each day's close
    def by(x, w):
        return {k: float(v) for k, v in x.groupby(w).mean().items()}
    sun = r[wd == "Sunday"]
    rec, rec6 = sun.iloc[-(recent // 5):], sun.iloc[-(recent * 2 // 5):]
    last = pd.Timestamp(dates[-1])
    next_day = WEEKDAYS[(WEEKDAYS.index(last.day_name()) + 1) % 5] if last.day_name() in WEEKDAYS else None
    return {"next_day_after": by(nxt.dropna(), wd[nxt.notna()]), "same_day": by(r, wd),
            "recent": {"sessions": int(len(rec)), "sunday": float(rec.mean()), "sunday_down": float((rec < 0).mean()),
                       "sunday_6m": float(rec6.mean())},
            "next_session": next_day,
            "show": bool(next_day == "Thursday" and rec.mean() < -0.001 and rec6.mean() < -0.001)}


# ------------------------------------------------------------ journey & verdict
# What the share is doing now: its last month (vs its own usual monthly move) and this week,
# not where it stands against an old swing low. "Usual monthly move" = daily swing x sqrt(20), 4-15%.
PHASES = ["Rising", "Rising, dipping", "Turning down", "Sideways, lifting", "Sideways", "Sideways, slipping",
          "Turning up", "Falling, bouncing", "Falling"]
PHASE_TEXT = {
    "Rising": "up over the last month and still rising this week",
    "Rising, dipping": "up over the last month, dipping this week",
    "Turning down": "up over the last month but has given back much of it from its recent high",
    "Sideways, lifting": "flat over the last month, lifting this week",
    "Sideways": "flat over the last month",
    "Sideways, slipping": "flat over the last month, slipping this week",
    "Turning up": "down over the last month but lifting clearly off its recent low",
    "Falling, bouncing": "down over the last month, bouncing a little this week",
    "Falling": "down over the last month and still falling this week",
}
# The 1-month plan is a race: buy today, sell when the day's high reaches the take-profit (a resting
# sell order) or on the first close at the share's own stop-loss (from its supports and volatility,
# see features.dynamic_stop), or at the end of the month if neither comes.
COST = 0.01           # round-trip brokerage and fees
TIER = {"Buy": 2, "Neutral": 1, "Sell": 0}
# Tag rules: fixed levels, no ranking against other shares (tested on unseen days in analyze.py).
# lead = chance(take-profit first) - chance(stop first); dev2y = price vs its usual level
# (2-year average, or last year's average when the share moved to a new price range).
BUY_LEAD = 0.15       # Buy: lead of +15 points or more,
JUNK_LEAD = 0.25      #      +25 for operator / junk shares (their odds are less reliable),
BUY_MAX_DEV = 0.0     #      price below its usual level (cheap by its own history),
NO_BUY_PHASES = ("Turning down",)   # not while a rise is being given back,
DRASTIC_RET5 = -0.10  #      not in a drastic fall (10%+ down in a week, a limit-down day in 4 weeks, or RSI below 35),
DRASTIC_RSI = 35      #      and a falling share (Falling / Falling, bouncing, or 5%+ down in a week) only once it shows a turn:
FALL_RET5 = -0.05     #      a higher 10-day low, its 5-day average back above the 10-day average, or 3%+ off its 10-day low
TURN_OFF_LOW = 0.03
GLOOMY, HOT = 0.30, 0.70   # market mood: share of all shares above their 20-day average. Below 30% (gloomy) or
                           # above 70% (overheated), Buy only shares doing better than the market over the last month
SELL_DEV = 0.20       # Sell: stop more likely first while the price is at or above its usual level,
                      #       or the price is 20%+ above its usual level without a +15 lead


def race(close, days, goal, stop, high=None):
    """Per day and share: +1 if its take-profit came first, -1 if its stop came first, 0 if neither; and the trade result.

    The take-profit is a resting sell order, so it counts as reached when the day's high gets
    there (sold at the take-profit even if the share closes lower). The stop is checked on the
    close. When both happen on the same day the take-profit filled first, during the session.
    """
    cv, sv, gv = close.values, stop.values, goal.values
    hv = cv if high is None else high.reindex_like(close).values
    lab = np.full(cv.shape, np.nan)
    res = np.full(cv.shape, np.nan)
    for t in range(len(close) - days):
        path = cv[t + 1:t + days + 1] / cv[t] - 1
        up, dn = hv[t + 1:t + days + 1] / cv[t] - 1 >= gv[t], path <= -sv[t]
        iu = np.where(up.any(0), up.argmax(0), days + 1)
        idn = np.where(dn.any(0), dn.argmax(0), days + 1)
        l = np.where(iu <= idn, 1.0, -1.0)
        l[(iu > days) & (idn > days)] = 0.0
        l[np.isnan(cv[t]) | np.isnan(path[-1]) | np.isnan(sv[t]) | np.isnan(gv[t])] = np.nan
        lab[t] = l
        res[t] = np.where(l == 1, gv[t], np.where(l == -1, -sv[t], path[-1]))
    return (pd.DataFrame(lab, index=close.index, columns=close.columns),
            pd.DataFrame(res, index=close.index, columns=close.columns))


def trade_value(pt, ps, goal, stop, flat_avg):
    """Expected result of the trade after costs: +goal, -stop, or the usual month-end move."""
    return goal * pt - stop * ps + flat_avg * (1 - pt - ps).clip(lower=0) - COST


def fall_state(phase, ret5, rsi, lc_hits20, higher_low, ma5_vs_ma10, off_low10):
    """Per share: drastic fall, still falling, and the turn-around signs seen (tested on unseen days in analyze.py)."""
    drastic = (ret5 < DRASTIC_RET5) | (lc_hits20 > 0) | (rsi < DRASTIC_RSI)
    falling = phase.isin(["Falling", "Falling, bouncing"]) | (ret5 < FALL_RET5)
    signs = pd.DataFrame({"higher 10-day low": higher_low > 0, "5-day average above 10-day": ma5_vs_ma10 > 0,
                          f"{TURN_OFF_LOW:.0%}+ off its 10-day low": off_low10 > TURN_OFF_LOW})
    return drastic.fillna(False), falling.fillna(False), signs.fillna(False)


def market_ok(breadth, ret20, mkt_ret20):
    """False when the market is gloomy or overheated and the share is not doing better than it."""
    return ~((breadth < GLOOMY) | (breadth > HOT)) | (ret20 > mkt_ret20)


def race_tag(pt, ps, phase, junk, dev2y, drastic=False, falling=False, turning=True, mkt_ok=True):
    lead = pt - ps
    need = np.where(junk, JUNK_LEAD, BUY_LEAD)
    buy = (lead >= need) & (dev2y < BUY_MAX_DEV) & ~phase.isin(NO_BUY_PHASES) & ~drastic & (~falling | turning) & mkt_ok
    sell = ((ps > pt) & (dev2y >= 0)) | ((dev2y > SELL_DEV) & (lead < BUY_LEAD))
    return pd.Series(np.select([buy, sell], ["Buy", "Sell"], "Neutral"), index=pt.index)


def phase(ret5, ret20, dist_ma20, vol20, dd20, up20):
    """What the share is doing now, from its last month and this week (see PHASE_TEXT)."""
    mv = (vol20 * np.sqrt(20)).clip(0.04, 0.15)                # its usual 1-month move
    up = (ret20 > 0.5 * mv) & (dist_ma20 > 0)
    dn = (ret20 < -0.5 * mv) & (dist_ma20 < 0)
    return pd.Series(np.select(
        [up & (dd20 < -0.6 * mv), up & (ret5 < 0), up,
         dn & (up20 > 0.5 * mv) & (ret5 > 0), dn & (ret5 > 0), dn,
         ret5 > 0.4 * mv, ret5 < -0.4 * mv],
        ["Turning down", "Rising, dipping", "Rising", "Turning up", "Falling, bouncing", "Falling",
         "Sideways, lifting", "Sideways, slipping"], "Sideways"), index=ret5.index)


def path_quantiles(fwd_wide, days):
    """Each share's own spread of outcomes over the period: 25th, 50th, 75th percentile."""
    f = fwd_wide.clip(*CLIP)
    return f.quantile(0.25), f.quantile(0.5), f.quantile(0.75)
