"""
Buy / Sell odds for two timeframes, move chance, confidence, reasons and rankings.

For each timeframe (features.HORIZONS) the target is the share's return over the
next `days` trading days:
    Buy  = rises more than `thr`   (short: +2% in a week, long: +10% in 2 months)
    Sell = falls more than `thr`
    Flat = anything in between
A gradient-boosted tree model learns the three outcomes; its odds are then
calibrated on walk-forward (unseen) predictions. The site shows:
    Move chance = odds of Buy + odds of Sell (will it move enough to matter?)
    Buy / Sell split = Buy odds / Move chance, and the rest (adds up to 100%)
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from .features import MODEL_ANGLES, MODEL_FEATURES as FEATURES
from .prep import NON_EQUITY

MIN_HISTORY = 60
SMOOTH_DAYS = 3
SECTOR_CAP = 4
TOP_N = 20
VERDICTS = [(0.72, "Strong Buy"), (0.58, "Buy"), (0.50, "Lean Buy"),
            (0.42, "Lean Sell"), (0.28, "Sell"), (-1, "Strong Sell")]


def labels(fwd, thr):
    return pd.Series(np.select([fwd > thr, fwd < -thr], [2, 0], 1), index=fwd.index)


def new_model():
    return HistGradientBoostingClassifier(
        max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=400,
        l2_regularization=1.0, random_state=0)


def fit(panel, fwd, thr, last_date):
    d = panel.index.get_level_values("date")
    ok = fwd.notna().values & (panel["history_days"].values >= MIN_HISTORY) & (d <= last_date)
    X = panel.loc[ok, FEATURES]
    mdl = new_model().fit(X, labels(fwd[ok], thr))
    mdl.medians_ = X.median()
    return mdl


def predict(mdl, X):
    p = mdl.predict_proba(X[FEATURES])
    return pd.DataFrame(p, index=X.index, columns=["sell", "flat", "buy"])


def walk_forward(panel, fwd, thr, days, dates, start=280, step=20):
    """Out-of-sample odds: retrain every `step` days on outcomes already known at the time."""
    parts = []
    d = panel.index.get_level_values("date")
    for i in range(start, len(dates), step):
        known = dates[i - days - 1]          # last day whose outcome was known on day i
        mdl = fit(panel, fwd, thr, known)
        window = (d >= dates[i]) & (d <= dates[min(i + step, len(dates)) - 1])
        parts.append(predict(mdl, panel.loc[window]))
    return pd.concat(parts).sort_index()


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


class _Platt:
    """
    Smooth, order-keeping map from raw odds to real frequencies. The slope comes from
    the unseen (walk-forward) predictions; the level is then shifted so the average
    matches the full two-year base rate, not just the test months (which were a rally).
    """

    def fit(self, raw, hit, base_rate):
        lr = LogisticRegression(C=1e6).fit(_logit(raw)[:, None], hit)
        self.a, self.b = float(lr.intercept_[0]), float(lr.coef_[0, 0])
        z = self.a + self.b * _logit(raw)
        lo, hi = -10.0, 10.0
        for _ in range(60):                     # bisection on the level shift
            mid = (lo + hi) / 2
            if (1 / (1 + np.exp(-(z + mid)))).mean() > base_rate:
                hi = mid
            else:
                lo = mid
        self.a += (lo + hi) / 2
        return self

    def __call__(self, raw):
        return 1 / (1 + np.exp(-(self.a + self.b * _logit(raw))))


class Calibrator:
    """Maps raw odds to how often Buy / Sell really happened."""

    def fit(self, oos, fwd, thr, base_buy, base_sell):
        f = fwd.reindex(oos.index)
        ok = f.notna().values
        self.buy = _Platt().fit(oos["buy"].values[ok], (f[ok] > thr).astype(int).values, base_buy)
        self.sell = _Platt().fit(oos["sell"].values[ok], (f[ok] < -thr).astype(int).values, base_sell)
        return self

    def apply(self, prob):
        b = self.buy(prob["buy"].values)
        s = self.sell(prob["sell"].values)
        total = b + s
        scale = np.where(total > 0.97, 0.97 / total, 1.0)
        return scores(pd.DataFrame({"sell": s * scale, "buy": b * scale}, index=prob.index))


def scores(prob):
    """Add move chance and the Buy/Sell split (direction) to buy/sell odds."""
    out = prob[["buy", "sell"]].copy()
    out["move"] = out["buy"] + out["sell"]
    out["direction"] = (out["buy"] / out["move"].replace(0, np.nan)).fillna(0.5)
    return out


def verdict(direction):
    for cut, name in VERDICTS:
        if direction >= cut:
            return name
    return VERDICTS[-1][1]


def smooth(prob):
    """Average of the last SMOOTH_DAYS days per stock, so rankings don't flicker."""
    s = prob.groupby(level="symbol").rolling(SMOOTH_DAYS, min_periods=1).mean()
    s.index = s.index.droplevel(0)
    s = s.sort_index()
    return s.div(s.sum(axis=1), axis=0)


def angle_contributions(mdl, X):
    """
    Points of (Buy odds - Sell odds) each angle adds: reset that angle's features to
    their typical (median) value and measure how much the edge changes.
    """
    base = predict(mdl, X)
    edge = base["buy"] - base["sell"]
    out = {}
    for angle, cols in MODEL_ANGLES.items():
        Xa = X.copy()
        for c in cols:
            Xa[c] = mdl.medians_[c]
        p = predict(mdl, Xa)
        out[angle] = (edge - (p["buy"] - p["sell"])) * 100
    return pd.DataFrame(out)


def confidence(row_panel, sc, btype):
    """0-100: how far to trust today's split for this stock."""
    hist = (row_panel["history_days"] / 250).clip(0, 1)
    liq = row_panel["liq_value"].rank(pct=True).fillna(0)
    reg = (row_panel["regularity"].fillna(0) / 0.5).clip(0, 1) * (row_panel["n_legs"].fillna(0) / 6).clip(0, 1)
    clarity = ((sc["direction"] - 0.5).abs() / 0.3).clip(0, 1)
    base = 0.20 * hist + 0.30 * liq + 0.20 * reg + 0.30 * clarity
    mult = btype.map({"dead": 0.5, "junk": 0.75, "new": 0.5}).fillna(1.0)
    return (100 * base * mult).clip(0, 100).round(0)


def rank_score(buy, sell, conf):
    """
    Buy odds minus Sell odds. Backtests showed the model is much better at spotting
    likely fallers than risers, so the best buys have good upside with little downside;
    ranking on Buy odds alone picked volatile junk. Confidence only breaks near-ties.
    """
    return (buy - sell) + 0.0002 * conf


def sell_score(buy, sell, conf):
    """
    Odds of falling, lightly offset by odds of rising. Not the mirror of rank_score:
    flat shares have near-zero Buy odds, and a plain Sell-minus-Buy would list them
    as sells even though they rarely fall either.
    """
    return (sell - 0.5 * buy) + 0.0002 * conf


def top_list(table, n=TOP_N, cap=SECTOR_CAP, score="rank_score"):
    """Top n by score, at most `cap` per sector; returns (top, also_strong by sector)."""
    ordered = table[~table["sector"].isin(NON_EQUITY)].sort_values(score, ascending=False)
    picked, count, also = [], {}, {}
    for sym, row in ordered.iterrows():
        if len(picked) >= n:
            break
        sec = row["sector"]
        if count.get(sec, 0) < cap:
            picked.append(sym)
            count[sec] = count.get(sec, 0) + 1
        elif len(also.setdefault(sec, [])) < 3:
            also[sec].append(sym)      # skipped only because the sector is full
    return picked, {s: v for s, v in also.items() if v}


def day_table(prob, panel_day, btype_day, info):
    """One day's scores for every share: odds, split, confidence, verdict, ranks."""
    t = scores(prob)
    t["sector"] = info["sector"].reindex(t.index)
    t["conf"] = confidence(panel_day.reindex(t.index), t, btype_day.reindex(t.index))
    t["rank_score"] = rank_score(t["buy"], t["sell"], t["conf"])
    t["sell_score"] = sell_score(t["buy"], t["sell"], t["conf"])
    t["rank"] = t["rank_score"].rank(ascending=False, method="first").astype(int)
    t["verdict"] = t["direction"].map(verdict)
    return t
