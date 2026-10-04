# dse-data
Dhaka Stock Exchange data, plus a daily scoring site built from it.

## What runs automatically

| When (Dhaka) | Workflow | What it does |
|---|---|---|
| Sun–Thu 2:47 PM | Daily prices | Downloads today's prices, rebuilds the site (marked *preliminary*) |
| Sun–Thu 4:07 PM | Daily prices | Re-checks the last 5 days, rebuilds the site (*final*) |
| Sun–Thu 5:23 PM | Daily prices | Backup: same as 4:07 PM, in case GitHub skipped an earlier run |
| Sat 10:00 PM | Weekly fundamentals | Refreshes every company page (category, holdings, dividends) |

## Files

- `data/prices.csv`: daily prices for every instrument
- `data/fundamentals.csv`: weekly company snapshots
- `data/signals.csv`: each day's 1-month plan for every share: chance of reaching +5% before −5% (and the reverse), expected result, journey phase, tag (Buy / Neutral / Sell), confidence and rank. It's a forward record the model can never revise.
- `update.py`: the downloader
- `analyze.py` + `analysis/`: the scoring pipeline
  - `prep.py`: loads the data and corrects bonus-share / dividend price drops
  - `features.py`: cycles, 2-year regular range, how far the day's high usually reaches and 3-month swing bands, money flow, junk pattern, market mood, and more
  - `model.py`: the model and the calibrated +5% / −5% race odds
  - `expected.py`: the 1-month race (sell at +5%, −5% or after 20 trading days), tag rules, expected result, journey phase (bottoming, early/mid/late rise, topping, early/mid/late fall), verdict rules, projected path, and calendar statistics
  - `backtest.py`: the honest track record
  - `report.py`: the site's data files
- `site/`: the website (plain HTML/JS). `analyze.py` writes its data into `site/data/`.

Run locally: `pip install -r requirements.txt && python analyze.py`, then `python -m http.server -d site` and open http://localhost:8000.

## The 1-month plan

Goal: at least +5% within a month. Buy today; keep a sell order at the share's take-profit (it fills when the day's high reaches it, any day), or exit on a close at its stop-loss, or by the sell-by date one month later.
- **Take-profit per share** (never below +5%): just under the nearest resistance (3-month high, usual price level, or top of the 2-year regular range) if it is 5%+ away and within the share's usual monthly move (max 15%); otherwise +5%.
- **Stop-loss per share**: just under the 20-day low (else the 3-month low) less half a normal day's move, if 3–12% below the price; otherwise the share's usual 2-week swing (4–12%).
- **Usual price level**: the 2-year average, or last year's average when the share moved to a new price range (last year's average 30%+ away from the year before's).
- **Lead** = chance of take-profit first − chance of stop first.
- **Buy** (all must hold, fixed levels, no ranking against other shares): lead of +15 or more (+25 for operator / junk shares), price below its usual level, not Topping or in a Mid fall, not in a drastic fall (10%+ down in a week, a limit-down day in 4 weeks, or RSI below 35), and a falling share (Early / Late fall, or 5%+ down in a week) must show a turn: a higher 10-day low, its 5-day average back above the 10-day, or 3%+ off its 10-day low.
- **Sell** (either one): the stop is more likely first while the price is at or above its usual level, or the price is 20%+ above it without a +15 lead.
- **Neutral**: everything else. Each share gets a written rationale, its price vs its 2-year average, and a "what changed since the last session" list.

On unseen days Buys reached their take-profit first ~60% of the time vs the stop ~17% (a random share: ~51% / ~26%), about +0.9% per trade after ~1% costs; Sells lost ~0.2% per trade after costs. The take-profit counts as reached when the day's high gets there (a resting sell order), the stop on the close.

## One-time setup for the website

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. On a free GitHub plan, Pages only works for **public** repositories (Settings → General → Danger zone → Change visibility).
3. Run **Actions → Daily prices → Run workflow** once. The site then appears at `https://<your-user>.github.io/dse-data/`.
