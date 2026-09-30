"""
Expected 2-week price change and the verdict.

    expected change = odds outlook + cycle tilt + month season + weekday effect

- Odds outlook: calibrated chance of a >3% rise x the average such rise, plus the
  chance of a >3% fall x the average such fall, plus the rest x the average small
  move (averages from the full history).
- Cycle tilt: average excess return seen in each zone of the 2-year range.
- Month season: how periods centred on this calendar month did for the average
  share versus normal (Q4 is DSE's dry season).
- Weekday effect: how periods bought on this weekday did versus normal
  (Thursday is the last trading day before DSE's Friday-Saturday weekend).
The cycle tilt changes the order of shares, so it is kept only if it improves the
Top 20. Month and weekday effects move every share equally, so they are kept only
if they make the expected change more accurate on unseen periods. Both calendar
effects are halved because two years give only a couple of samples each.
"""

import numpy as np
import pandas as pd

CLIP = (-0.40, 0.60)          # keep one-off pumps from dominating averages
CYCLE_EDGES = [-9, 0, 0.25, 0.5, 0.75, 1, 9]
CYCLE_ZONES = ["below regular low", "bottom quarter", "2nd quarter", "3rd quarter", "top quarter", "above regular high"]
SHRINK = 0.5
CYCLE_WEIGHTS = [0.5, 1.0, 2.0]
VERDICT_CUTS = [(0.04, "Strong Buy"), (0.025, "Buy"), (0.01, "Lean Buy")]
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]


def verdict(exp):
    for cut, name in VERDICT_CUTS:
        if exp >= cut:
            return name
    return "Sell"


def outcome_averages(fwd_wide, universe, thr):
    """Average return over the period when a share rose past thr, fell past -thr, or neither."""
    f = fwd_wide[universe].clip(*CLIP).stack()
    return {"up": float(f[f > thr].mean()), "down": float(f[f < -thr].mean()),
            "flat": float(f[(f >= -thr) & (f <= thr)].mean())}


def outlook(odds, avg):
    """Expected change implied by calibrated buy/sell odds."""
    flat = (1 - odds["buy"] - odds["sell"]).clip(lower=0)
    return odds["buy"] * avg["up"] + odds["sell"] * avg["down"] + flat * avg["flat"]


def excess_target(fwd_wide, universe):
    """Share return minus the average share's return over the same days (both clipped)."""
    f = fwd_wide.clip(*CLIP)
    return f.sub(f[universe].mean(axis=1), axis=0)


# ------------------------------------------------------------ cycle tilt
def cycle_table(band, y):
    zone = pd.cut(band, CYCLE_EDGES, labels=CYCLE_ZONES)
    return y.groupby(zone, observed=False).mean().fillna(0)


def cycle_values(table, band):
    zone = pd.cut(band, CYCLE_EDGES, labels=CYCLE_ZONES)
    return pd.Series(zone.map(table).astype(float).values, index=band.index).fillna(0)


def cycle_walk_forward(panel, y, days, dates, start=280, step=20):
    """Cycle tilt for unseen days, each learned only from outcomes known at the time."""
    parts = []
    d = panel.index.get_level_values("date")
    for i in range(start, len(dates), step):
        known = (d <= dates[i - days - 1]) & y.notna().values
        table = cycle_table(panel.loc[known, "band_all"], y[known])
        window = (d >= dates[i]) & (d <= dates[min(i + step, len(dates)) - 1])
        parts.append(cycle_values(table, panel.loc[window, "band_all"]))
    return pd.concat(parts).sort_index()


# ------------------------------------------------------------ calendar effects
def season_month(date, days):
    """Month a period mostly falls in (its midpoint): a 2-week buy on 30 Sep is an October trade."""
    return (pd.Timestamp(date) + pd.Timedelta(days=int(days * 0.7))).strftime("%m")


def weekday(date):
    return pd.Timestamp(date).day_name()


def market_path(fwd_wide, universe):
    """Return of the average share over the period starting each day (clipped)."""
    return fwd_wide[universe].clip(*CLIP).mean(axis=1).dropna()


def calendar_tables(mk, days, until=None):
    """Half-shrunk month and weekday effects learned from periods that ended by `until`."""
    x = mk if until is None else mk[mk.index <= until]
    base = float(x.mean())
    month = x.groupby([season_month(d, days) for d in x.index]).mean()
    wday = x.groupby([weekday(d) for d in x.index]).mean()
    return {"base": base,
            "month": ((month - base) * SHRINK).to_dict(), "month_raw": month.to_dict(),
            "weekday": ((wday - base) * SHRINK).to_dict(), "weekday_raw": wday.to_dict(),
            "month_n": x.groupby([season_month(d, days) for d in x.index]).size().to_dict()}


def calendar_adjust(tables, date, days, use_month, use_weekday):
    m = tables["month"].get(season_month(date, days), 0.0) if use_month else 0.0
    w = tables["weekday"].get(weekday(date), 0.0) if use_weekday else 0.0
    return m, w


def thursday_stats(close, universe, dates):
    """Next-trading-day return of the average share after each weekday's close."""
    r = close[universe].pct_change(fill_method=None).shift(-1).clip(-0.2, 0.2)
    nxt = r.mean(axis=1).dropna()
    by = nxt.groupby([weekday(d) for d in nxt.index]).mean()
    same = close[universe].pct_change(fill_method=None).clip(-0.2, 0.2).mean(axis=1).dropna()
    by_day = same.groupby([weekday(d) for d in same.index]).mean()
    return {"next_day_after": {k: float(v) for k, v in by.items()},
            "same_day": {k: float(v) for k, v in by_day.items()}}
