"""
Buy / Hold / Sell probabilities, confidence, per-angle reasons, and rankings.

Target: the stock's return over the next HORIZON trading days.
    Buy  = more than +2%   (clears ~1% round-trip costs with something left)
    Sell = less than -2%
    Hold = anything in between
A gradient-boosted tree model learns these from every feature; its three
probabilities add up to 100%.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from .features import ANGLES, FEATURES, HORIZON
from .prep import NON_EQUITY

BUY_T, SELL_T = 0.02, -0.02
MIN_HISTORY = 60
SMOOTH_DAYS = 3
SECTOR_CAP = 4
TOP_N = 20


def labels(fwd):
    return pd.Series(np.select([fwd > BUY_T, fwd < SELL_T], [2, 0], 1), index=fwd.index)


def new_model():
    return HistGradientBoostingClassifier(
        max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=400,
        l2_regularization=1.0, random_state=0)


def training_rows(panel, fwd, last_date):
    d = panel.index.get_level_values("date")
    ok = fwd.notna().values & (panel["history_days"].values >= MIN_HISTORY) & (d <= last_date)
    return ok


def fit(panel, fwd, last_date):
    ok = training_rows(panel, fwd, last_date)
    X = panel.loc[ok, FEATURES]
    mdl = new_model().fit(X, labels(fwd[ok]))
    mdl.medians_ = X.median()
    return mdl


def predict(mdl, X):
    p = mdl.predict_proba(X[FEATURES])
    return pd.DataFrame(p, index=X.index, columns=["sell", "hold", "buy"])


def walk_forward(panel, fwd, dates, start=280, step=20):
    """Out-of-sample probabilities: retrain every `step` days on data known at the time."""
    parts = []
    d = panel.index.get_level_values("date")
    for i in range(start, len(dates), step):
        known = dates[i - HORIZON - 1]          # last day whose 5-day outcome is known at day i
        mdl = fit(panel, fwd, known)
        window = (d >= dates[i]) & (d <= dates[min(i + step, len(dates)) - 1])
        parts.append(predict(mdl, panel.loc[window]))
    return pd.concat(parts).sort_index()


class Calibrator:
    """
    Maps raw model probabilities to how often Buy / Sell actually happened, using
    the walk-forward (unseen) predictions. Hold is what is left.
    """

    def fit(self, oos, fwd):
        f = fwd.reindex(oos.index)
        ok = f.notna()
        self.buy = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
            oos.loc[ok, "buy"], (f[ok] > BUY_T).astype(float))
        self.sell = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
            oos.loc[ok, "sell"], (f[ok] < SELL_T).astype(float))
        return self

    def apply(self, prob):
        b = self.buy.predict(prob["buy"].values)
        s = self.sell.predict(prob["sell"].values)
        total = b + s
        scale = np.where(total > 0.95, 0.95 / total, 1.0)
        b, s = b * scale, s * scale
        return pd.DataFrame({"sell": s, "hold": 1 - b - s, "buy": b}, index=prob.index)


def smooth(prob):
    """Average of the last SMOOTH_DAYS days per stock, so rankings don't flicker."""
    s = prob.groupby(level="symbol").rolling(SMOOTH_DAYS, min_periods=1).mean()
    s.index = s.index.droplevel(0)
    s = s.sort_index()
    return s.div(s.sum(axis=1), axis=0)


def angle_contributions(mdl, X):
    """
    How much each angle moves (Buy% - Sell%), in percentage points: reset that
    angle's features to the typical (median) value and see how the edge changes.
    """
    base = predict(mdl, X)
    edge = base["buy"] - base["sell"]
    out = {}
    for angle, cols in ANGLES.items():
        Xa = X.copy()
        for c in cols:
            Xa[c] = mdl.medians_[c]
        p = predict(mdl, Xa)
        out[angle] = (edge - (p["buy"] - p["sell"])) * 100
    return pd.DataFrame(out)


def confidence(row_panel, prob, btype):
    """0-100: how far to trust the split for this stock today."""
    hist = (row_panel["history_days"] / 250).clip(0, 1)
    liq = row_panel["liq_value"].rank(pct=True).fillna(0)
    reg = (row_panel["regularity"].fillna(0) / 0.5).clip(0, 1) * (row_panel["n_legs"].fillna(0) / 6).clip(0, 1)
    top2 = np.sort(prob[["sell", "hold", "buy"]].values, axis=1)
    clarity = pd.Series(((top2[:, 2] - top2[:, 1]) / 0.3).clip(0, 1), index=prob.index)
    base = 0.20 * hist + 0.30 * liq + 0.20 * reg + 0.30 * clarity
    mult = btype.map({"dead": 0.5, "junk": 0.75, "new": 0.5}).fillna(1.0)
    return (100 * base * mult).clip(0, 100).round(0)


def rank_score(buy, sell, conf):
    """
    Buy% minus Sell%. Backtests showed the model is much better at spotting likely
    fallers than risers, so the best buys are good upside with little downside;
    ranking on Buy% alone picked volatile junk. Confidence only breaks near-ties.
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
