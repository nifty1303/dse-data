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

Buy today; sell on the first close 5% higher (goal) or 5% lower (stop), or after one month if neither happens.
- **Buy**: chance of +5% first beats chance of −5% first by 10+ points, and the share is in today's top 10% by that edge.
- **Sell**: −5% first is more likely than +5% first (the price is more likely to fall).
- **Neutral**: everything else.

On unseen days the top 10% reached +5% first ~51% of the time vs −5% first ~28% (≈ +0.2% per trade after ~1% costs); the bottom 10% was stopped out ~45% of the time. The edge is real but thin.

## One-time setup for the website

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. On a free GitHub plan, Pages only works for **public** repositories (Settings → General → Danger zone → Change visibility).
3. Run **Actions → Daily prices → Run workflow** once. The site then appears at `https://<your-user>.github.io/dse-data/`.
