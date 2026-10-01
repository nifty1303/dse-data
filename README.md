# dse-data
Dhaka Stock Exchange data, plus a daily scoring site built from it.

## What runs automatically

| When (Dhaka) | Workflow | What it does |
|---|---|---|
| Sun–Thu 2:45 PM | Daily prices | Downloads today's prices, rebuilds the site (marked *preliminary*) |
| Sun–Thu 4:00 PM | Daily prices | Re-checks the last 5 days, rebuilds the site (*final*) |
| Sat 10:00 PM | Weekly fundamentals | Refreshes every company page (category, holdings, dividends) |

## Files

- `data/prices.csv`: daily prices for every instrument
- `data/fundamentals.csv`: weekly company snapshots
- `data/signals.csv`: each day's 1-month plan for every share: chance of reaching +5% before −5% (and the reverse), expected result, journey phase, tag (Buy / Neutral / Sell), confidence and rank. It's a forward record the model can never revise.
- `update.py`: the downloader
- `analyze.py` + `analysis/`: the scoring pipeline
  - `prep.py`: loads the data and corrects bonus-share / dividend price drops
  - `features.py`: cycles, 2-year regular range and 3-month swing bands, money flow, junk pattern, market mood, and more
  - `model.py`: the model and the calibrated +5% / −5% race odds
  - `expected.py`: the 1-month race (sell at +5%, −5% or after 20 trading days), tag rules, expected result, journey phase (bottoming, early/mid/late rise, topping, early/mid/late fall), verdict rules, projected path, and calendar statistics
  - `backtest.py`: the honest track record
  - `report.py`: the site's data files
- `site/`: the website (plain HTML/JS). `analyze.py` writes its data into `site/data/`.

Run locally: `pip install -r requirements.txt && python analyze.py`, then `python -m http.server -d site` and open http://localhost:8000.

## The 1-month plan

Goal: +5% within a month. Buy today; sell on the first close at +5% (any day), or at the share's own stop-loss, or by the sell-by date one month later.
- **Stop-loss per share**: just under the 20-day low (else the 3-month low) less half a normal day's move, if 3–12% below the price; otherwise the share's usual 2-week swing (4–12%).
- **Lead** = chance of +5% first − chance of the stop first. Tags come from the lead alone, plus a journey check.
- **Buy** (all must hold): lead in today's top 10% and at least +10 points (+20 for operator / junk shares), and the share is not Topping or in a Mid fall.
- **Sell**: the stop is more likely to come first than +5%.
- **Neutral**: everything else. Each share gets a written rationale, its price vs its 2-year average, and a "what changed since the last session" list.

On unseen days Buys reached +5% first ~57% of the time vs the stop ~18% (a random share: ~43% / ~29%); after ~1% costs that is about break-even per trade. Sells reached +5% first only ~40% and lost ~0.8% per trade after costs.

## One-time setup for the website

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. On a free GitHub plan, Pages only works for **public** repositories (Settings → General → Danger zone → Change visibility).
3. Run **Actions → Daily prices → Run workflow** once. The site then appears at `https://<your-user>.github.io/dse-data/`.
