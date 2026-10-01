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


def thursday_stats(close, universe, dates):
    """Next-trading-day return of the average share after each weekday's close."""
    r = close[universe].pct_change(fill_method=None).shift(-1).clip(-0.2, 0.2)
    nxt = r.mean(axis=1).dropna()
    by = nxt.groupby([weekday(d) for d in nxt.index]).mean()
    same = close[universe].pct_change(fill_method=None).clip(-0.2, 0.2).mean(axis=1).dropna()
    by_day = same.groupby([weekday(d) for d in same.index]).mean()
    return {"next_day_after": {k: float(v) for k, v in by.items()},
            "same_day": {k: float(v) for k, v in by_day.items()}}


# ------------------------------------------------------------ journey & verdict
# Where the share is on its current swing, from the causal swing detector.
PHASES = ["Bottoming", "Early rise", "Mid rise", "Late rise", "Topping", "Early fall", "Mid fall", "Late fall", "Sideways"]
PHASE_TEXT = {
    "Bottoming": "a long fall that has started turning up",
    "Early rise": "early in a new rise",
    "Mid rise": "midway through a rise",
    "Late rise": "a rise that is running longer than usual",
    "Topping": "a long rise that has started turning down",
    "Early fall": "early in a new fall",
    "Mid fall": "midway through a fall",
    "Late fall": "a fall that is running longer than usual",
    "Sideways": "no clear swing",
}
# The 1-month plan is a race: buy today, sell on the first close at +5% (the goal) or at
# the share's own stop-loss (from its supports and volatility, see features.dynamic_stop),
# or at the end of the month if neither comes.
COST = 0.01           # round-trip brokerage and fees
TIER = {"Buy": 2, "Neutral": 1, "Sell": 0}
# Tag rules (tested on unseen days in analyze.py):
BUY_LEAD = 0.10       # Buy: chance(+5% first) beats chance(stop first) by 10+ points
BUY_TOP = 0.10        #      and among the top 10% of shares by expected result today
SELL_BOTTOM = 0.10    # Sell: stop more likely first than +5% (more likely to fall),
                      #       or among the bottom 10% of shares by expected result today


def race(close, days, goal, stop):
    """Per day and share: +1 if +goal came first, -1 if the stop came first, 0 if neither; and the trade result."""
    cv, sv = close.values, stop.values
    lab = np.full(cv.shape, np.nan)
    res = np.full(cv.shape, np.nan)
    for t in range(len(close) - days):
        path = cv[t + 1:t + days + 1] / cv[t] - 1
        up, dn = path >= goal, path <= -sv[t]
        iu = np.where(up.any(0), up.argmax(0), days + 1)
        idn = np.where(dn.any(0), dn.argmax(0), days + 1)
        l = np.where(iu < idn, 1.0, np.where(idn < iu, -1.0, 0.0))
        l[np.isnan(cv[t]) | np.isnan(path[-1]) | np.isnan(sv[t])] = np.nan
        lab[t] = l
        res[t] = np.where(l == 1, goal, np.where(l == -1, -sv[t], path[-1]))
    return (pd.DataFrame(lab, index=close.index, columns=close.columns),
            pd.DataFrame(res, index=close.index, columns=close.columns))


def trade_value(pt, ps, goal, stop, flat_avg):
    """Expected result of the trade after costs: +goal, -stop, or the usual month-end move."""
    return goal * pt - stop * ps + flat_avg * (1 - pt - ps).clip(lower=0) - COST


def race_tag(pt, ps, value, universe=None):
    """Returns (tag, today's Buy bar, today's Sell bar) on expected result."""
    ref = value if universe is None else value[value.index.isin(universe)]
    buy_bar = float(ref.quantile(1 - BUY_TOP)) if len(ref) else np.inf
    sell_bar = float(ref.quantile(SELL_BOTTOM)) if len(ref) else -np.inf
    buy = (pt - ps >= BUY_LEAD) & (value >= buy_bar)
    sell = (ps > pt) | (value <= sell_bar)
    return pd.Series(np.select([buy, sell], ["Buy", "Sell"], "Neutral"), index=pt.index), buy_bar, sell_bar


def phase(leg_dir, progress, ret5):
    """Vectorised journey phase from swing direction, progress vs typical length, and this week's move."""
    up, down = leg_dir == 1, leg_dir == -1
    late = progress >= 1.0
    early = progress < 0.5
    return pd.Series(np.select(
        [up & late & (ret5 < 0), up & late, up & early, up,
         down & late & (ret5 > 0), down & late, down & early, down],
        ["Topping", "Late rise", "Early rise", "Mid rise", "Bottoming", "Late fall", "Early fall", "Mid fall"],
        "Sideways"), index=leg_dir.index)


def path_quantiles(fwd_wide, days):
    """Each share's own spread of outcomes over the period: 25th, 50th, 75th percentile."""
    f = fwd_wide.clip(*CLIP)
    return f.quantile(0.25), f.quantile(0.5), f.quantile(0.75)
