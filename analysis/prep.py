"""
Load the raw CSVs, correct for bonus/dividend drops, and build date x symbol tables.

DSE caps daily moves at about 10%, so a one-day drop well beyond that on a stock
above 2 Tk is a record-date adjustment (bonus shares, big cash dividend, rights),
not a real crash. Prices before such a day are scaled down so the history is
continuous; volumes are scaled up by the same factor.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PRICES_CSV = "data/prices.csv"
FUNDAMENTALS_CSV = "data/fundamentals.csv"

CIRCUIT_DROP = -0.105       # beyond DSE's ~10% daily limit
MIN_PRICE_FOR_ACTION = 2.0  # sub-2 Tk stocks jump >10% on a single tick
NON_EQUITY = {"Corporate Bond", "Debenture"}


@dataclass
class Market:
    dates: pd.Index
    symbols: pd.Index
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame          # adjusted
    raw_close: pd.DataFrame      # as traded
    volume: pd.DataFrame         # adjusted share count
    value: pd.DataFrame          # Tk million
    trade: pd.DataFrame
    traded: pd.DataFrame         # bool: at least one trade that day
    info: pd.DataFrame           # one row per symbol (sector, category, ...)
    actions: pd.DataFrame        # detected corporate actions
    index: pd.DataFrame = field(default=None)   # market index series
    sector_ret: pd.DataFrame = field(default=None)  # date x sector daily return


def _wide(df, col):
    return df.pivot(index="date", columns="symbol", values=col)


def detect_actions(raw_close, open_, skip=()):
    """Return (date, symbol, factor) rows; factor < 1 multiplies prices before date.

    A record-date adjustment also shows as an opening gap (DSE resets the reference
    price); a plain sell-off opens near yesterday's close and slides from there.
    """
    prev = raw_close.shift(1)
    r = raw_close / prev - 1
    gap = open_ / prev
    hits = (r < CIRCUIT_DROP) & (gap < 0.97) & (prev >= MIN_PRICE_FOR_ACTION)
    hits.loc[:, hits.columns.isin(list(skip))] = False
    rows = []
    for date, sym in zip(*np.where(hits.values)):
        d, s = raw_close.index[date], raw_close.columns[sym]
        pc, o, c = prev.iat[date, sym], open_.iat[date, sym], raw_close.iat[date, sym]
        f = o / pc
        # Bonus issues come in round percentages; snap when the gap is close to one.
        bonus = 1 / f - 1
        snapped = round(bonus / 0.05) * 0.05
        if snapped >= 0.05 and abs(bonus - snapped) < 0.02:
            f = 1 / (1 + snapped)
        rows.append({"date": d, "symbol": s, "prev_close": pc, "open": o, "close": c,
                     "factor": round(f, 4), "est_pct": round((1 / f - 1) * 100, 1)})
    return pd.DataFrame(rows, columns=["date", "symbol", "prev_close", "open", "close", "factor", "est_pct"])


def load():
    p = pd.read_csv(PRICES_CSV)
    p = p.drop_duplicates(["date", "symbol"], keep="last")
    f = pd.read_csv(FUNDAMENTALS_CSV)
    f = f[f["snapshot_date"] == f["snapshot_date"].max()].set_index("symbol")

    close = _wide(p, "close").sort_index()
    close = close.where(close > 0).ffill()
    volume = _wide(p, "volume").reindex_like(close).fillna(0)
    traded = volume > 0
    # No trades: DSE repeats yesterday's close and leaves open/high/low at 0.
    open_ = _wide(p, "open").reindex_like(close).where(traded).fillna(close)
    high = _wide(p, "high").reindex_like(close).where(traded).fillna(close)
    low = _wide(p, "low").reindex_like(close).where(traded).fillna(close)
    value = _wide(p, "value").reindex_like(close).fillna(0)
    trade = _wide(p, "trade").reindex_like(close).fillna(0)
    raw_close = close.copy()

    bonds = f.index[f["sector"].isin(NON_EQUITY)]
    actions = detect_actions(raw_close, open_, skip=bonds)
    adj = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    for a in actions.itertuples():
        adj.loc[adj.index < a.date, a.symbol] *= a.factor
    close, open_, high, low = close * adj, open_ * adj, high * adj, low * adj
    volume = volume / adj

    symbols = close.columns
    info = pd.DataFrame(index=symbols)
    for col in ["sector", "market_category", "paid_up_capital_mn", "outstanding_shares",
                "face_value", "reserve_mn", "sponsor_pct", "govt_pct", "institute_pct",
                "foreign_pct", "public_pct", "market_cap_mn"]:
        info[col] = f[col].reindex(symbols) if col in f else np.nan
    info["sector"] = info["sector"].fillna("Unknown")
    info["market_category"] = info["market_category"].replace("-", np.nan).fillna("?")
    info["is_equity"] = ~info["sector"].isin(NON_EQUITY)
    info["is_fund"] = info["sector"].eq("Mutual Funds")
    info["first_date"] = raw_close.apply(lambda s: s.first_valid_index())

    m = Market(close.index, symbols, open_, high, low, close, raw_close, volume, value,
               trade, traded, info, actions)
    build_indexes(m)
    return m


def build_indexes(m):
    """Market index (cap weighted, shares companies only) and equal-weight sector returns."""
    ret = m.close.pct_change(fill_method=None).clip(-0.5, 0.5)
    stocks = m.info.index[m.info["is_equity"] & ~m.info["is_fund"]]
    shares = m.info["outstanding_shares"].reindex(stocks).fillna(0)
    # Adjusted close x today's share count keeps weights continuous across bonus issues.
    cap = m.close[stocks].mul(shares, axis=1)
    w = cap.shift(1)
    w = w.div(w.sum(axis=1), axis=0)
    idx_ret = (ret[stocks] * w).sum(axis=1)
    eq_ret = ret[stocks].mean(axis=1)
    m.index = pd.DataFrame({
        "cap_ret": idx_ret, "eq_ret": eq_ret,
        "cap_level": 1000 * (1 + idx_ret.fillna(0)).cumprod(),
        "eq_level": 1000 * (1 + eq_ret.fillna(0)).cumprod(),
        "turnover": m.value[stocks].sum(axis=1),
    })
    m.sector_ret = ret.T.groupby(m.info["sector"]).mean().T
