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
- `data/signals.csv`: each day's 2-week (10 trading days) expected move, journey phase, verdict (Strong Buy / Buy / Sell / Strong Sell), odds, confidence and rank for every share. It's a forward record the model can never revise.
- `update.py`: the downloader
- `analyze.py` + `analysis/`: the scoring pipeline
  - `prep.py`: loads the data and corrects bonus-share / dividend price drops
  - `features.py`: cycles, 2-year regular range and 3-month swing bands, money flow, junk pattern, market mood, and more
  - `model.py`: the model and the calibrated Buy / Sell odds
  - `expected.py`: expected 2-week move, journey phase (bottoming, early/mid/late rise, topping, early/mid/late fall), verdict rules, projected path, and calendar statistics
  - `backtest.py`: the honest track record
  - `report.py`: the site's data files
- `site/`: the website (plain HTML/JS). `analyze.py` writes its data into `site/data/`.

Run locally: `pip install -r requirements.txt && python analyze.py`, then `python -m http.server -d site` and open http://localhost:8000.

## One-time setup for the website

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. On a free GitHub plan, Pages only works for **public** repositories (Settings → General → Danger zone → Change visibility).
3. Run **Actions → Daily prices → Run workflow** once. The site then appears at `https://<your-user>.github.io/dse-data/`.
