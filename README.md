# 200W

A mobile-friendly static site that finds Nasdaq-100 stocks trading near or below their 200-week moving average.

## How it works

- Market data comes from Alpha Vantage `TIME_SERIES_WEEKLY_ADJUSTED`.
- The signal uses the latest adjusted weekly close and the arithmetic mean of the latest 200 adjusted weekly closes.
- Distance is calculated as `(price / 200-week average - 1) × 100%`.
- The free Alpha Vantage service is limited to 25 requests per day, so the updater scans a rotating batch and resumes from its saved cursor on the next run. Each cycle scans watchlist stocks first, then the remaining Nasdaq-100 stocks in list order, without duplicates.
- Listings with fewer than 200 weeks of history are recorded with a future retry date and skipped until then.

## Local setup

Create a private environment file:

```bash
cp .env.local.example .env.local
```

Add your Alpha Vantage key to `.env.local`:

```dotenv
ALPHA_VANTAGE_API_KEY=your_key
DAILY_LIMIT=25
```

The file is ignored by Git. The API key never reaches the browser or GitHub.

Run the daily update:

```bash
./scripts/local_update.sh
```

Each invocation updates up to 25 eligible stocks, skips excluded and young listings, and continues from `data/update-state.json` without repeating stocks within the current cycle. The wrapper does not restrict how many times it can run per day.

## Local preview

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000>.

## Lists

- Add symbols to `data/blacklist.json` to exclude them from both scanning and the signal lists.
- Add symbols to `data/watchlist.json` to keep them in the prominent Watchlist section and scan them first in each cycle. Symbols outside the Nasdaq-100 pool are supported, and duplicate entries are scanned only once.

Both files use a JSON array:

```json
["AAPL", "MSFT"]
```

## GitHub Pages deployment

1. In the repository, open **Settings → Pages** and select **GitHub Actions** as the source.
2. Run the updater locally.
3. Commit `data/stocks.json` and `data/update-state.json`, then push to `main`.
4. The Pages workflow publishes the static site. GitHub only receives the generated market data, never the API key.

Every deployment stamps the page assets with the pushed commit and publishes a version marker. An open page checks that marker every 30 seconds and reloads automatically after a newer deployment becomes available.

The constituent list reflects the Nasdaq-100 June 2026 quarterly changes. For research only; not investment advice.
