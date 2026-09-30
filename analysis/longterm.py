"""
Expected 2-month price change for the long-term view.

    expected change = outlook from the odds + cycle tilt + seasonal adjustment

- Outlook from the odds: the calibrated chance of a big rise (>10%) times the
  average big rise, plus the chance of a big fall times the average big fall, plus
  the rest times the average small move (averages from the full history).
  On unseen data, shares scored +5-10% this way gained a median +7% with the
  fewest 10%+ falls, so this is where the stock-level skill comes from.
- Cycle tilt: the average excess return seen in each zone of the 2-year range,
  learned walk-forward. Its weight is picked by the backtest and stays at zero
  unless it improves the Top 20. (In testing it did not: the cycle position mostly
  times the whole market rather than separating shares.)
- Seasonal adjustment: how 2-month periods starting in this calendar month did for
  the average share versus normal, shrunk halfway to zero (two years = two samples).
  Q4 is DSE's dry season (turnover ~60-75% of normal).
Verdicts follow the owner's rule: under +5% Sell, +5% to +15% Lean Buy, 15%+ Strong Buy.
"""

import numpy as np
import pandas as pd

CLIP = (-0.40, 0.60)          # keep one-off pumps from dominating averages
CYCLE_EDGES = [-9, 0, 0.25, 0.5, 0.75, 1, 9]
CYCLE_ZONES = ["below regular low", "bottom quarter", "2nd quarter", "3rd quarter", "top quarter", "above regular high"]
SEASON_SHRINK = 0.5
BLEND_WEIGHTS = [0.0, 0.5, 1.0, 2.0]
VERDICT_CUTS = [(0.15, "Strong Buy"), (0.05, "Lean Buy")]


def verdict(exp):
    for cut, name in VERDICT_CUTS:
        if exp >= cut:
            return name
    return "Sell"


def outcome_averages(fwd_wide, universe, thr):
    """Average 2-month return when a share rose past thr, fell past -thr, or neither."""
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


def season_month(date):
    """Month a period starting on `date` mostly falls in: a start on 30 Sep is an October trade."""
    return (pd.Timestamp(date) + pd.Timedelta(days=15)).strftime("%m")


def seasonality(fwd_wide, universe):
    """2-month return of the average share by season month (see season_month)."""
    mk = fwd_wide[universe].clip(*CLIP).mean(axis=1).dropna()
    base = float(mk.mean())
    by_month = mk.groupby([season_month(d) for d in mk.index]).mean()
    samples = mk.groupby(mk.index.str[:7]).mean()
    adj = ((by_month - base) * SEASON_SHRINK).reindex([f"{i:02d}" for i in range(1, 13)]).fillna(0)
    return base, adj, by_month, samples
