"""
Everything measured about every stock on every day, without looking ahead.

Each feature is a date x symbol table computed only from data up to that date,
so the same numbers serve today's scores and the historical backtest.
Features are grouped into the angles shown on the site (ANGLES).
"""

import numpy as np
import pandas as pd

HORIZON = 5        # one trading week: sets the swing-detection threshold
# The timeframe scored: one month = 20 DSE trading days (Sun-Thu, about 1 Oct -> 1 Nov),
# with a +5% profit goal. thr is also the band for the rise / fall odds.
HORIZONS = {
    "short": {"days": 20, "thr": 0.05, "label": "1 month", "after": "month", "long_label": "next 20 trading days"},
}
RANGE_DAYS = 500   # "regular range" = up to 2 years of history (all we have for now)
ANALOG_K = 7


# ------------------------------------------------------------ helpers
def _sum(df, w, minp=None):
    return df.rolling(w, min_periods=minp or max(2, w // 2)).sum()


def _mean(df, w, minp=None):
    return df.rolling(w, min_periods=minp or max(2, w // 2)).mean()


def _median(df, w, minp=None):
    return df.rolling(w, min_periods=minp or max(2, w // 2)).median()


def _q(df, w, q, minp):
    return df.rolling(w, min_periods=minp).quantile(q)


def _log_ratio(a, b):
    return np.log((a + 1e-9) / (b + 1e-9))


# ------------------------------------------------------------ swings (causal zigzag)
def zigzag(close, thr):
    """
    Walk forward through one stock's closes. A swing high is confirmed once the
    price falls `thr` below it (and vice versa), so every value at day t uses only
    data up to t. Returns per-day arrays and the list of confirmed pivots.
    """
    n = len(close)
    out = {k: np.full(n, np.nan) for k in
           ["leg_dir", "leg_days", "leg_move", "up_len", "dn_len", "up_pct", "dn_pct",
            "n_legs", "regularity"]}
    pivots = []          # (index, price, kind) kind: +1 high, -1 low
    legs = []            # (dir, length, pct)
    direction = 0        # 0 = not yet known, 1 = rising leg, -1 = falling leg
    hi_i = lo_i = start = None
    for t in range(n):
        c = close[t]
        if np.isnan(c):
            continue
        th = 0.10 if np.isnan(thr[t]) else thr[t]
        if hi_i is None:
            hi_i = lo_i = start = t
        if direction >= 0 and c > close[hi_i]:
            hi_i = t
        if direction <= 0 and c < close[lo_i]:
            lo_i = t
        if direction >= 0 and c <= close[hi_i] * (1 - th):
            if direction == 1:
                legs.append((1, hi_i - start, close[hi_i] / close[start] - 1))
            pivots.append((hi_i, close[hi_i], 1))
            direction, start, lo_i = -1, hi_i, t
        elif direction <= 0 and c >= close[lo_i] * (1 + th):
            if direction == -1:
                legs.append((-1, lo_i - start, close[lo_i] / close[start] - 1))
            pivots.append((lo_i, close[lo_i], -1))
            direction, start, hi_i = 1, lo_i, t
        if direction != 0:
            out["leg_dir"][t] = direction
            out["leg_days"][t] = t - start
            out["leg_move"][t] = c / close[start] - 1
        ups = [l for l in legs if l[0] == 1]
        dns = [l for l in legs if l[0] == -1]
        out["n_legs"][t] = len(legs)
        if ups:
            out["up_len"][t] = np.median([l[1] for l in ups[-6:]])
            out["up_pct"][t] = np.median([l[2] for l in ups[-6:]])
        if dns:
            out["dn_len"][t] = np.median([l[1] for l in dns[-6:]])
            out["dn_pct"][t] = np.median([l[2] for l in dns[-6:]])
        if len(legs) >= 3:
            lens = np.array([l[1] for l in legs[-8:]], float)
            out["regularity"][t] = float(np.clip(1 - lens.std() / (lens.mean() + 1e-9), 0, 1))
    return out, pivots


# ------------------------------------------------------------ main
def build(m):
    """Return (panel, wide, extras). panel: long (date, symbol) feature table."""
    c, h, l, o = m.close, m.high, m.low, m.open
    v, val, tr = m.volume, m.value, m.trade
    ret = c.pct_change(fill_method=None).fillna(0).clip(-0.5, 0.5)
    W = {}

    # ---- A. cycle position
    # Regular range: 10th-90th percentile of up to 2 years (everything known on that day).
    # Outliers: the true lowest / highest close in that same window.
    # Current swing: the same percentiles over the last 60 days only.
    p10_all, p90_all = _q(c, RANGE_DAYS, 0.10, 120), _q(c, RANGE_DAYS, 0.90, 120)
    min_all = c.rolling(RANGE_DAYS, min_periods=120).min()
    max_all = c.rolling(RANGE_DAYS, min_periods=120).max()
    p10_60, p90_60 = _q(c, 60, 0.10, 40), _q(c, 60, 0.90, 40)
    max120 = c.rolling(120, min_periods=40).max()
    W["band_all"] = ((c - p10_all) / (p90_all - p10_all).replace(0, np.nan)).clip(-1, 2)
    W["band60"] = ((c - p10_60) / (p90_60 - p10_60).replace(0, np.nan)).clip(-1, 2)
    up_room = (p90_all / c - 1).clip(-0.5, 2)
    down_risk = (1 - min_all / c).clip(0, 1)
    W["up_room"], W["down_risk"] = up_room, down_risk
    W["reward_risk"] = np.log((up_room.clip(lower=0) + 0.02) / (down_risk + 0.02)).clip(-3, 3)

    std60 = ret.rolling(60, min_periods=20).std()
    thr = (2 * std60 * np.sqrt(HORIZON)).clip(0.06, 0.25)
    zz = {k: pd.DataFrame(np.nan, index=c.index, columns=c.columns) for k in
          ["leg_dir", "leg_days", "leg_move", "up_len", "dn_len", "up_pct", "dn_pct", "n_legs", "regularity"]}
    pivots = {}
    for s in c.columns:
        out, piv = zigzag(c[s].values, thr[s].values)
        for k, arr in out.items():
            zz[k][s] = arr
        pivots[s] = piv
    typ_len = zz["up_len"].where(zz["leg_dir"] == 1, zz["dn_len"])
    typ_pct = zz["up_pct"].where(zz["leg_dir"] == 1, -zz["dn_pct"])
    W["leg_dir"] = zz["leg_dir"].fillna(0)
    W["leg_progress"] = (zz["leg_days"] / typ_len).clip(0, 3)
    W["leg_done"] = (zz["leg_move"].abs() / typ_pct.abs().replace(0, np.nan)).clip(0, 3)
    W["up_leg_young"] = ((W["leg_dir"] == 1) & (W["leg_progress"] < 0.6)).astype(float)
    W["down_leg_old"] = ((W["leg_dir"] == -1) & (W["leg_progress"] > 0.8)).astype(float)
    for k in ["leg_days", "leg_move", "up_len", "dn_len", "up_pct", "dn_pct", "n_legs", "regularity"]:
        W[k] = zz[k]

    # ---- B. trend & momentum
    for n in (5, 10, 20, 60):
        W[f"ret{n}"] = c / c.shift(n) - 1
    ma20, ma50 = _mean(c, 20), _mean(c, 50, 30)
    W["dist_ma20"] = (c / ma20 - 1).clip(-0.5, 0.5)
    W["dist_ma50"] = (c / ma50 - 1).clip(-0.5, 0.5)
    W["ma20_slope"] = (ma20 / ma20.shift(5) - 1).clip(-0.3, 0.3)
    gain = ret.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-ret.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    W["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    W["rsi"] = W["rsi"].fillna(50)
    W["higher_low"] = (l.rolling(10).min() / l.shift(10).rolling(10).min() - 1).clip(-0.5, 0.5)

    # ---- C. money flow
    med_v120 = _median(v, 120, 40)
    W["vol_ratio5"] = _log_ratio(_mean(v, 5), med_v120).clip(-4, 4)
    W["vol_ratio20"] = _log_ratio(_mean(v, 20), med_v120).clip(-4, 4)
    up_v = _sum(v.where(ret > 0, 0), 20)
    dn_v = _sum(v.where(ret < 0, 0), 20)
    W["updown_vol"] = _log_ratio(up_v, dn_v).clip(-4, 4)
    tsize = v / tr.replace(0, np.nan)
    W["trade_size"] = _log_ratio(_mean(tsize, 10, 3), _median(tsize, 120, 30)).clip(-3, 3).fillna(0)
    rng = (h - l).replace(0, np.nan)
    W["close_loc"] = _mean((((c - l) - (h - c)) / rng).fillna(0), 5)
    W["pv_diverge"] = (np.sign(W["ret10"]) * -W["vol_ratio20"]).clip(-4, 4)

    # ---- D. liquidity
    W["liq_value"] = np.log1p(_median(val, 60, 20))
    W["zero_days"] = _mean((v == 0).astype(float), 60, 20)
    W["med_trades"] = _median(tr, 60, 20)
    W["exit_days"] = (0.5 / _median(val, 60, 20).replace(0, np.nan)).clip(0, 50).fillna(50)  # days to sell Tk 0.5 mn at 100% of turnover

    # ---- E. risk
    W["vol20"] = ret.rolling(20, min_periods=10).std()
    W["vol60"] = std60
    W["uc_hits20"] = _sum((ret >= 0.095).astype(float), 20)
    W["lc_hits20"] = _sum((ret <= -0.095).astype(float), 20)
    W["drawdown120"] = (c / max120 - 1).clip(-1, 0)
    W["gap_down20"] = _sum((o / c.shift(1) - 1 < -0.05).astype(float), 20)

    # ---- F. relative strength & market
    mk = m.index
    mret5 = mk["cap_level"].pct_change(5)
    mret20 = mk["cap_level"].pct_change(20)
    sec_level = (1 + m.sector_ret.fillna(0)).cumprod()
    sec = m.info["sector"]
    s5 = (sec_level / sec_level.shift(5) - 1)[sec.values].set_axis(c.columns, axis=1)
    s20 = (sec_level / sec_level.shift(20) - 1)[sec.values].set_axis(c.columns, axis=1)
    W["rel_mkt5"] = W["ret5"].sub(mret5, axis=0)
    W["rel_mkt20"] = W["ret20"].sub(mret20, axis=0)
    W["rel_sec5"] = W["ret5"] - s5
    W["rel_sec20"] = W["ret20"] - s20
    W["sec_ret20"] = s20

    market = market_state(m, W, ret)
    for k in ["mkt_ret5", "mkt_ret20", "breadth", "adv_dec5", "turnover_trend", "mood"]:
        W[k] = pd.DataFrame(np.repeat(market[k].values[:, None], len(c.columns), axis=1),
                            index=c.index, columns=c.columns)

    # ---- G. fundamentals (latest weekly snapshot, held constant)
    info = m.info
    stat = pd.DataFrame(index=c.columns)
    for cat in "ABNZ":
        stat[f"cat_{cat}"] = (info["market_category"] == cat).astype(float)
    stat["is_fund"] = info["is_fund"].astype(float)
    stat["is_bond"] = (~info["is_equity"]).astype(float)
    stat["log_mcap"] = np.log1p(info["market_cap_mn"].fillna(0))
    stat["log_paidup"] = np.log1p(info["paid_up_capital_mn"].fillna(0))
    stat["sponsor_pct"] = info["sponsor_pct"].fillna(0) / 100
    stat["institute_pct"] = info["institute_pct"].fillna(0) / 100
    stat["foreign_pct"] = info["foreign_pct"].fillna(0) / 100
    stat["public_pct"] = info["public_pct"].fillna(0) / 100
    stat["reserve_neg"] = (info["reserve_mn"].fillna(0) < 0).astype(float)
    for k in stat.columns:
        W[k] = pd.DataFrame(np.repeat(stat[k].values[None, :], len(c.index), axis=0),
                            index=c.index, columns=c.columns)
    face = info["face_value"].replace(0, np.nan)
    W["px_face"] = np.log(m.raw_close / face).clip(-3, 6)

    # ---- H. junk pattern & behaviour type
    spikes = (v > 5 * med_v120).astype(float)
    W["spikes250"] = _sum(spikes, 250, 60)
    W["uc_hits250"] = _sum((ret >= 0.095).astype(float), 250, 60)
    W["pump250"] = W["ret20"].rolling(250, min_periods=60).max().clip(0, 3)
    er_num = np.log(c / c.shift(120)).abs()
    er_den = np.log1p(ret).abs().rolling(120, min_periods=60).sum()
    W["trend_eff"] = (er_num / er_den.replace(0, np.nan)).clip(0, 1)
    junk = junk_score(W, stat)
    W["junk_score"] = junk
    btype = behaviour_type(W, junk)
    stage = junk_stage(W, c, v, med_v120)
    for k in ["accumulation", "markup", "distribution", "dump"]:
        W[f"stage_{k}"] = (stage == k).astype(float)
    for k in ["cycler", "trender", "junk", "dead"]:
        W[f"type_{k}"] = (btype == k).astype(float)
    W["cyc_x_band"] = W["type_cycler"] * (0.5 - W["band_all"].fillna(0.5))
    W["junk_x_markup"] = W["type_junk"] * W["stage_markup"]
    W["junk_x_dist"] = W["type_junk"] * W["stage_distribution"]

    # ---- I. similar past setups, for each timeframe
    fwd, fwd_max, analogs = {}, {}, {}
    for key, hz in HORIZONS.items():
        fwd[key] = c.shift(-hz["days"]) / c - 1
        # best close reached within the period (did it touch the profit goal at any point?)
        fwd_max[key] = c.rolling(hz["days"]).max().shift(-hz["days"]) / c - 1
        a_ret, a_win, analogs[key] = analog_features(W, fwd[key], hz["days"])
        W[f"analog_ret_{key}"], W[f"analog_win_{key}"] = a_ret, a_win

    history_days = c.notna().cumsum()
    W["history_days"] = history_days

    panel = pd.concat({k: W[k].stack(future_stack=True) for k in FEATURES + INFO_COLS}, axis=1)
    panel.index.names = ["date", "symbol"]
    extras = {"pivots": pivots, "btype": btype, "stage": stage, "market": market,
              "fwd": fwd, "fwd_max": fwd_max, "analogs": analogs, "bands": {"p10_60": p10_60, "p90_60": p90_60,
              "p10_all": p10_all, "p90_all": p90_all, "min_all": min_all, "max_all": max_all},
              "wide": W}
    return panel, extras


def market_state(m, W, ret):
    eq = m.info.index[m.info["is_equity"] & ~m.info["is_fund"]]
    mk = m.index
    ma20 = _mean(m.close[eq], 20)
    traded = m.traded[eq]
    df = pd.DataFrame(index=m.dates)
    df["mkt_ret5"] = mk["cap_level"].pct_change(5)
    df["mkt_ret20"] = mk["cap_level"].pct_change(20)
    df["eq_ret20"] = mk["eq_level"].pct_change(20)
    df["breadth"] = (m.close[eq] > ma20).where(ma20.notna()).mean(axis=1)
    up = ((ret[eq] > 0) & traded).sum(axis=1)
    dn = ((ret[eq] < 0) & traded).sum(axis=1)
    df["adv_dec5"] = ((up - dn).rolling(5).sum() / (up + dn).rolling(5).sum()).fillna(0)
    to = mk["turnover"]
    df["turnover_trend"] = np.log(to.rolling(20, min_periods=10).mean() / to.rolling(120, min_periods=40).mean())
    df["near_low"] = (W["band60"][eq] < 0.2).mean(axis=1)
    df["near_high"] = (W["band60"][eq] > 0.8).mean(axis=1)
    df["up_count"], df["down_count"] = up, dn
    df["turnover"] = to
    # -1 (hostile) .. +1 (friendly)
    score = (np.tanh(df["mkt_ret20"].fillna(0) / 0.05) * 0.35
             + (df["breadth"].fillna(0.5) - 0.5) * 2 * 0.30
             + df["adv_dec5"] * 0.20
             + np.tanh(df["turnover_trend"].fillna(0)) * np.sign(df["mkt_ret20"].fillna(0)) * 0.15)
    df["mood"] = score.clip(-1, 1)
    return df


def junk_score(W, stat):
    """0..1 cross-sectional rank blend of pump-and-dump traits."""
    parts = [
        W["spikes250"].rank(axis=1, pct=True),
        W["uc_hits250"].rank(axis=1, pct=True),
        W["pump250"].rank(axis=1, pct=True),
        W["vol60"].rank(axis=1, pct=True),
        (-W["log_paidup"]).rank(axis=1, pct=True),
    ]
    score = sum(parts) / len(parts)
    score = score + 0.15 * W["cat_Z"] + 0.05 * W["cat_B"] - 0.10 * W["cat_A"]
    return score.clip(0, 1)


def behaviour_type(W, junk):
    t = pd.DataFrame("mixed", index=junk.index, columns=junk.columns)
    cycler = (W["n_legs"] >= 4) & (W["regularity"] >= 0.35)
    trender = W["trend_eff"] >= 0.30
    dead = (W["med_trades"] < 15) | (W["zero_days"] > 0.25) | (np.expm1(W["liq_value"]) < 0.3)
    t = t.mask(cycler, "cycler").mask(trender, "trender").mask(junk >= 0.62, "junk").mask(dead, "dead")
    return t.where(W["liq_value"].notna(), "new")


def junk_stage(W, c, v, med_v120):
    vr5 = v.rolling(5, min_periods=3).mean() / med_v120
    vr10 = v.rolling(10, min_periods=5).mean() / med_v120
    vr20 = v.rolling(20, min_periods=10).mean() / med_v120
    max20, min20 = c.rolling(20, min_periods=10).max(), c.rolling(20, min_periods=10).min()
    max40, min40 = c.rolling(40, min_periods=20).max(), c.rolling(40, min_periods=20).min()
    s = pd.DataFrame("quiet", index=c.index, columns=c.columns)
    accum = (max20 / min20 - 1 < 0.12) & (vr20 > 1.1) & (vr20 < 3) & (W["trade_size"] > 0.1)
    markup = (W["ret10"] > 0.15) & (vr10 > 2)
    distrib = (max20 / min40 - 1 > 0.25) & (c / max20 > 0.85) & (W["ret5"] >= -0.06) & (W["ret5"] <= 0.04) & (vr5 > 1.5)
    dump = (c / max40 < 0.80) & (W["ret5"] < -0.05)
    return s.mask(accum, "accumulation").mask(markup, "markup").mask(distrib, "distribution").mask(dump, "dump")


ANALOG_KEYS = ["band_all", "band60", "leg_dir", "leg_progress", "ret5", "ret20", "vol_ratio5", "updown_vol", "rsi"]
ANALOG_SCALE = {"ret5": 10, "ret20": 5, "rsi": 1 / 25, "leg_progress": 0.5}


def analog_features(W, fwd, horizon):
    """For each stock and day: outcome of the K most similar earlier days of the same stock."""
    idx, cols = fwd.index, fwd.columns
    a_ret = pd.DataFrame(np.nan, index=idx, columns=cols)
    a_win = pd.DataFrame(np.nan, index=idx, columns=cols)
    latest = {}
    for s in cols:
        X = np.column_stack([
            (W[k][s].values - (50 if k == "rsi" else 0)) * ANALOG_SCALE.get(k, 1) for k in ANALOG_KEYS])
        f = fwd[s].values
        ok = ~np.isnan(X).any(axis=1)
        T = len(idx)
        D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
        tt, ss = np.meshgrid(np.arange(T), np.arange(T), indexing="ij")
        valid = (ss <= tt - horizon) & ok[None, :] & ok[:, None] & ~np.isnan(f)[None, :]
        D = np.where(valid, D, np.inf)
        r_arr, w_arr = np.full(T, np.nan), np.full(T, np.nan)
        for t in range(T):
            if valid[t].sum() < 20:
                continue
            nn = np.argpartition(D[t], ANALOG_K)[:ANALOG_K]
            r_arr[t] = f[nn].mean()
            w_arr[t] = (f[nn] > 0).mean()
            if t == T - 1:
                nn = nn[np.argsort(D[t][nn])]
                latest[s] = [(str(idx[i]), float(f[i])) for i in nn]
        a_ret[s], a_win[s] = r_arr, w_arr
    return a_ret.clip(-0.6, 0.6), a_win, latest


# ------------------------------------------------------------ feature list
ANGLES = {
    "Cycle position": ["band_all", "band60", "reward_risk", "leg_dir", "leg_progress", "leg_done",
                       "up_leg_young", "down_leg_old", "cyc_x_band"],
    "Trend & momentum": ["ret5", "ret10", "ret20", "ret60", "dist_ma20", "dist_ma50", "ma20_slope",
                         "rsi", "higher_low"],
    "Money flow": ["vol_ratio5", "vol_ratio20", "updown_vol", "trade_size", "close_loc", "pv_diverge"],
    "Liquidity": ["liq_value", "zero_days"],
    "Risk": ["vol20", "vol60", "uc_hits20", "lc_hits20", "drawdown120", "gap_down20"],
    "Relative strength": ["rel_mkt5", "rel_mkt20", "rel_sec5", "rel_sec20", "sec_ret20"],
    "Market mood": ["mkt_ret5", "mkt_ret20", "breadth", "adv_dec5", "turnover_trend", "mood"],
    "Fundamentals": ["cat_A", "cat_B", "cat_Z", "is_fund", "is_bond", "log_mcap", "sponsor_pct",
                     "institute_pct", "foreign_pct", "reserve_neg", "px_face"],
    "Junk pattern": ["junk_score", "spikes250", "pump250", "stage_accumulation", "stage_markup",
                     "stage_distribution", "stage_dump", "type_junk", "type_dead", "type_cycler",
                     "type_trender", "junk_x_markup", "junk_x_dist"],
    "Similar setups": ["analog_ret_short", "analog_win_short"],
}
FEATURES = [f for fs in ANGLES.values() for f in fs]
# Market mood is the same for every share and, with only ~2 years (one or two market
# regimes), a model that uses it learns "what the market did then" instead of which
# shares beat others. Backtests improved without it, so it drives the warning banner only.
MODEL_ANGLES = {a: cols for a, cols in ANGLES.items() if a != "Market mood"}
MODEL_FEATURES = [f for fs in MODEL_ANGLES.values() for f in fs]
INFO_COLS = ["up_room", "down_risk", "leg_days", "leg_move", "up_len", "dn_len", "up_pct", "dn_pct",
             "n_legs", "regularity", "exit_days", "med_trades", "trend_eff", "uc_hits250", "history_days"]
