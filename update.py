"""
DSE data updater, run by GitHub Actions.

    python update.py today                 # today only (Dhaka date)
    python update.py daily                 # last LOOKBACK_DAYS days (default 5)
    python update.py daily 10              # last 10 days
    python update.py fix 2026-09-29        # replace one day
    python update.py fix 2026-09-01 2026-09-10   # replace a range
    python update.py fundamentals          # refresh all company pages
"""

import os, re, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests, urllib3
import pandas as pd
from bs4 import BeautifulSoup

# ------------------------------------------------------------ settings
DATA_DIR = "data"
PRICES_CSV = f"{DATA_DIR}/prices.csv"
FUNDAMENTALS_CSV = f"{DATA_DIR}/fundamentals.csv"
LOOKBACK_DAYS = 5
MARKET_READY_TIME = "15:30"   # Dhaka time
PAUSE_SECONDS = 2

# DSE's new site (since 2026-09-24) no longer has these pages; the legacy site does.
# Its certificate chain is incomplete, so verification is skipped (public data only).
DSE_BASES = ["https://old.dsebd.org/", "https://old.dse.com.bd/"]
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research)"}
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PRICE_COLS = ["date", "symbol", "ltp", "high", "low", "open", "close", "ycp", "trade", "value", "volume"]
FUND_COLS = ["snapshot_date", "symbol", "sector", "market_category", "paid_up_capital_mn",
             "market_cap_mn", "outstanding_shares", "face_value", "reserve_mn",
             "sponsor_pct", "govt_pct", "institute_pct", "foreign_pct", "public_pct",
             "year_end", "cash_dividend", "bonus_issue", "right_issue", "last_agm"]
SAMPLE_ROWS = f"{DATA_DIR}/samples/company_page_rows.txt"


# ------------------------------------------------------------ basic tools
def get_page(path, params=None):
    for base in DSE_BASES:
        try:
            r = requests.get(base + path, params=params, headers=HEADERS, timeout=60, verify=False)
            if r.ok:
                return r.text
        except requests.RequestException as e:
            print(f"  {base}{path} failed: {e}")
    return None


def to_num(x):
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_csv(path, columns):
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=columns)


# ------------------------------------------------------------ prices
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fetch_prices(start, end):
    html = get_page("day_end_archive.php",
                    {"startDate": start, "endDate": end, "inst": "All Instrument", "archive": "data"})
    if html is None:
        return pd.DataFrame(columns=PRICE_COLS)
    rows = []
    for tr in BeautifulSoup(html, "lxml").find_all("tr"):
        c = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(c) >= 12 and DATE_RE.match(c[1]):
            rows.append([c[1], c[2]] + [to_num(v) for v in c[3:12]])
    df = pd.DataFrame(rows, columns=PRICE_COLS)
    return df[~df["symbol"].str.startswith("TB")]


def merge_prices(prices, new, replace_range=False):
    if new.empty:
        return prices
    if replace_range:
        prices = prices[~prices["date"].between(new["date"].min(), new["date"].max())]
    prices = (pd.concat([prices, new])
                .drop_duplicates(["date", "symbol"], keep="last")
                .sort_values(["date", "symbol"], ascending=[False, True])
                .reset_index(drop=True))
    prices.to_csv(PRICES_CSV, index=False)
    return prices


def daily(lookback=LOOKBACK_DAYS):
    prices = load_csv(PRICES_CSV, PRICE_COLS)
    now = datetime.now(ZoneInfo("Asia/Dhaka"))
    ready = now.strftime("%H:%M") >= MARKET_READY_TIME
    end = now.date() if ready else now.date() - timedelta(days=1)
    start = end - timedelta(days=lookback)

    new = fetch_prices(start.isoformat(), end.isoformat())
    before = len(prices)
    prices = merge_prices(prices, new)

    print(f"Dhaka time {now:%Y-%m-%d %H:%M}")
    print(f"Checked {start} to {end}: {len(new):,} rows downloaded, {len(prices) - before:,} new")
    print("Latest trading day:", prices["date"].max())
    today = now.date().isoformat()
    if ready and prices["date"].max() == today:
        print(f"OK: today ({today}) included, {(prices['date'] == today).sum()} instruments")
    elif ready:
        print(f"Note: today ({today}) not in the data (holiday, weekend, or not published yet)")

    if new.empty:
        # Nothing at all for several days usually means the site is down or has changed.
        # Failing the run makes GitHub email you.
        sys.exit("ERROR: DSE returned no price data for the whole range.")


def today():
    # Early same-day run. DSE may not have published yet, so an empty result is not an
    # error here; the later "daily" run re-checks the last few days and fails loudly.
    prices = load_csv(PRICES_CSV, PRICE_COLS)
    now = datetime.now(ZoneInfo("Asia/Dhaka"))
    day = now.date().isoformat()
    new = fetch_prices(day, day)
    before = len(prices)
    prices = merge_prices(prices, new)
    print(f"Dhaka time {now:%Y-%m-%d %H:%M}")
    if new.empty:
        print(f"Note: no data for {day} yet (holiday, or not published yet)")
    else:
        print(f"OK: {day}: {len(new):,} rows downloaded, {len(prices) - before:,} new")


def fix(start, end=None):
    end = end or start
    prices = load_csv(PRICES_CSV, PRICE_COLS)
    new = fetch_prices(start, end)
    if new.empty:
        sys.exit(f"ERROR: DSE returned no data for {start} to {end}; nothing changed.")
    merge_prices(prices, new, replace_range=True)
    print(f"Replaced {start} to {end} with {len(new):,} rows")


# ------------------------------------------------------------ fundamentals
LABELS = {
    "paid-up capital": "paid_up_capital_mn",
    "market capitalization": "market_cap_mn",
    "total no. of outstanding securities": "outstanding_shares",
    "face/par value": "face_value",
    "reserve & surplus without oci": "reserve_mn",
    "sector": "sector",
    "market category": "market_category",
    # Dividend history and year end (text as shown on the page, e.g. "10%B 2024, 15% 2023").
    "year end": "year_end",
    "cash dividend": "cash_dividend",
    "bonus issue": "bonus_issue",
    "right issue": "right_issue",
    "last agm held on": "last_agm",
}
TEXT_FIELDS = {"sector", "market_category", "year_end", "cash_dividend", "bonus_issue", "right_issue", "last_agm"}
# The page layout for EPS / NAV / P/E could not be checked when this was written, so the
# weekly run saves one company's matching rows here for the parser to be finished later.
SAMPLE_KEYWORDS = ("eps", "nav", "p/e", "dividend", "record date", "agm", "year end")
HOLDING_RE = re.compile(
    r"Sponsor/Director:\s*([\d.]+).*?Govt:\s*([\d.]+).*?Institute:\s*([\d.]+)"
    r".*?Foreign:\s*([\d.]+).*?Public:\s*([\d.]+)", re.S)


def save_sample_rows(symbol, soup):
    lines = [f"# {symbol} {date.today()}: table rows mentioning {', '.join(SAMPLE_KEYWORDS)}"]
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(k in " ".join(cells).lower() for k in SAMPLE_KEYWORDS):
            lines.append(" | ".join(cells))
    os.makedirs(os.path.dirname(SAMPLE_ROWS), exist_ok=True)
    with open(SAMPLE_ROWS, "w") as f:
        f.write("\n".join(lines) + "\n")


def fetch_fundamentals(symbol, sample=False):
    html = get_page("displayCompany.php", {"name": symbol})
    if html is None or "Paid-up Capital" not in html:
        return None
    soup = BeautifulSoup(html, "lxml")
    if sample:
        save_sample_rows(symbol, soup)
    out = {"snapshot_date": date.today().isoformat(), "symbol": symbol}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        for i in range(len(cells) - 1):
            label = cells[i].get_text(" ", strip=True).lower()
            for key, col in LABELS.items():
                if col not in out and label.startswith(key):
                    val = cells[i + 1].get_text(" ", strip=True)
                    out[col] = val if col in TEXT_FIELDS else to_num(val)
    holdings = HOLDING_RE.findall(soup.get_text(" "))
    if holdings:
        out.update(zip(["sponsor_pct", "govt_pct", "institute_pct", "foreign_pct", "public_pct"],
                       map(float, holdings[-1])))
    return out


def fundamentals():
    prices = load_csv(PRICES_CSV, PRICE_COLS)
    fund = load_csv(FUNDAMENTALS_CSV, FUND_COLS)
    symbols = sorted(prices.loc[prices["date"] == prices["date"].max(), "symbol"])
    rows, missing = [], []
    for i, sym in enumerate(symbols, 1):
        row = fetch_fundamentals(sym, sample=not rows)
        (rows.append(row) if row else missing.append(sym))
        if i % 50 == 0:
            print(f"[{i}/{len(symbols)}]")
        time.sleep(PAUSE_SECONDS)
    if not rows:
        sys.exit("ERROR: no company pages could be read.")
    fund = (pd.concat([fund, pd.DataFrame(rows, columns=FUND_COLS)])
              .drop_duplicates(["snapshot_date", "symbol"], keep="last")
              .sort_values(["snapshot_date", "symbol"], ascending=[False, True]))
    fund.to_csv(FUNDAMENTALS_CSV, index=False)
    print(f"Saved {len(rows)} companies; no page for {len(missing)} symbols")


# ------------------------------------------------------------ entry point
if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "today":
        today()
    elif cmd == "daily":
        daily(int(args[0]) if args else LOOKBACK_DAYS)
    elif cmd == "fix" and args:
        fix(*args[:2])
    elif cmd == "fundamentals":
        fundamentals()
    else:
        print(__doc__)
