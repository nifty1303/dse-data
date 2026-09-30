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
# Unseen-data check (Nov 2025 - Sep 2026): among shares expected to rise, those
# bottoming / late in a fall / early in a rise rose most often (~55%); among shares
# expected to fall, those still falling or topping rose least often (34-41%).
STRONG_BUY_PHASES = {"Bottoming", "Late fall", "Early rise"}
STRONG_SELL_PHASES = {"Early fall", "Mid fall", "Late fall", "Topping"}
STRONG_BUY_MIN = 0.01        # expected move of at least +1%
STRONG_SELL_MAX = -0.005     # expected move of -0.5% or worse
TIER = {"Strong Buy": 3, "Buy": 2, "Sell": 1, "Strong Sell": 0}


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


def journey_verdict(exp, ph):
    """Direction from the expected move, strength from the journey."""
    return pd.Series(np.select(
        [(exp >= STRONG_BUY_MIN) & ph.isin(STRONG_BUY_PHASES), exp > 0,
         (exp <= STRONG_SELL_MAX) & ph.isin(STRONG_SELL_PHASES)],
        ["Strong Buy", "Buy", "Strong Sell"], "Sell"), index=exp.index)


def path_quantiles(fwd_wide, days):
    """Each share's own spread of outcomes over the period: 25th, 50th, 75th percentile."""
    f = fwd_wide.clip(*CLIP)
    return f.quantile(0.25), f.quantile(0.5), f.quantile(0.75)
