# 200W

A mobile-friendly static site for comparing Wishlist, Nasdaq-100, and S&P 500 stocks with their 200-week moving averages.

## How it works

- Market data comes from Alpha Vantage `TIME_SERIES_WEEKLY_ADJUSTED`.
- Distance is calculated as `(latest adjusted weekly close / 200-week average - 1) × 100%`.
- The normal scan order is Wishlist → Nasdaq-100 → S&P 500. Symbols shared by multiple lists are scanned only once, and the scan cursor continues across batches.
- `data/blacklist.json` is shared by all three stock universes. Blacklisted stocks are never scanned and do not consume request quota.
- Stocks with less than 200 weeks of history are stored with an estimated retry date. They are skipped without consuming quota until that date, then automatically rejoin the scan plan.

## Local setup

Copy the private environment file and add your Alpha Vantage key:

```bash
cp .env.local.example .env.local
```

```dotenv
ALPHA_VANTAGE_API_KEY=your_key
DAILY_LIMIT=25
```

Run a scan:

```bash
./scripts/local_update.sh
```

When run interactively, the script asks whether to rescan the Wishlist first. Choosing `y` scans the Wishlist before resuming the saved plan with any remaining quota. A symbol is never requested twice within the same batch. You can also pass the option directly:

```bash
./scripts/local_update.sh --rescan-wishlist
```

A non-interactive run resumes the normal plan without an extra Wishlist scan. One Alpha Vantage key uses at most 25 requests per batch; set `DAILY_LIMIT` to use a smaller batch.

## Local preview

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000>. The first tab is Wishlist, followed by Nasdaq-100 and S&P 500. Wishlist cards show whether each stock belongs to either index.

## List files

- `data/watchlist.json`: Wishlist symbol array; stocks outside both indexes are supported.
- `data/blacklist.json`: shared blacklist symbol array.
- `data/nasdaq100.json`: Nasdaq-100 `[symbol, name]` snapshot.
- `data/sp500.json`: S&P 500 `[symbol, name]` snapshot.

Wishlist and blacklist example:

```json
["AAPL", "MSFT"]
```

To refresh the S&P 500 snapshot, download the constituents page and run:

```bash
python3 scripts/update_sp500.py /path/to/downloaded-page.html
```

## GitHub Pages deployment

After scanning, commit and push `data/stocks.json`, `data/update-state.json`, and any changed list files. GitHub Pages receives only generated market data—never `.env.local` or the API key.

The page checks `version.json` every 30 seconds. Once a new commit has been deployed, an open page reloads automatically. A locally generated update is not visible on a phone until it has been committed, pushed, and deployed.

For research only. Not investment advice.
