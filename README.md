# 200W

A mobile-friendly static site for comparing Wishlist, Nasdaq-100, and S&P 500 stocks with their 200-week moving averages.

## How it works

- Market data comes from Alpha Vantage `TIME_SERIES_WEEKLY_ADJUSTED`.
- Distance is calculated as `(latest adjusted weekly close / 200-week average - 1) × 100%`.
- The normal scan rotation is Nasdaq-100 → S&P 500, excluding every Wishlist symbol. Symbols shared by both indexes are scanned only once. The state stores both the cursor and the next symbol, so scanning continues where the previous batch stopped even if the queue definition changes.
- `data/blacklist.json` is shared by all three stock universes. Blacklisted stocks are never scanned and do not consume request quota.
- Stocks with less than 200 weeks of history are stored with an estimated retry date. They are skipped without consuming quota until that date, then automatically rejoin the scan plan.
- Initial coverage always takes priority: while any eligible stock has no stored result, previously scanned stocks are skipped without consuming quota. Normal refresh rotation starts only after the first coverage pass is complete.

## Local setup

Copy the private environment file and add one or both provider keys:

```bash
cp .env.local.example .env.local
```

```dotenv
ALPHA_VANTAGE_API_KEY=your_key
DAILY_LIMIT=25
TIINGO_API_KEY=your_tiingo_key
TIINGO_DAILY_LIMIT=50
```

Run a scan:

```bash
./scripts/local_update.sh
```

When run interactively, the script asks whether to scan the Wishlist in this run. Choosing `N` skips every Wishlist symbol and continues the normal Nasdaq-100 → S&P 500 rotation. Choosing `y` scans the Wishlist first, then resumes the saved normal plan with any remaining quota. A symbol is never requested twice within the same batch. You can also pass the option directly:

```bash
./scripts/local_update.sh --rescan-wishlist
```

A non-interactive run skips the Wishlist and resumes the normal plan. The updater uses Alpha Vantage first and automatically continues with Tiingo. `DAILY_LIMIT` controls Alpha Vantage requests (up to 25 per key), while `TIINGO_DAILY_LIMIT` controls Tiingo requests. With the defaults and both providers configured, one run can scan up to 75 stocks. Either provider can also be used on its own.

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

## Wishlist quarterly EPS

Wishlist EPS is scheduled every Saturday at 12:00 in `Europe/Amsterdam`, including daylight-saving changes. It uses Alpha Vantage `EARNINGS` and checks only Wishlist symbols, excluding blacklisted stocks. The EPS-only run uses up to `DAILY_LIMIT` requests (default 25). Successful checks are cached for 7 days; failures are eligible at the next scheduled run. Oldest checks run first if the list exceeds quota.

Prices retain their daily 10:00 schedule. On Saturdays, the daily workflow uses Tiingo for prices and reserves Alpha Vantage quota for the noon EPS run. Without a Tiingo key, Saturday prices wait for the next daily run. EPS scheduling is handled exclusively by GitHub Actions; no local cron or launchd task is installed. Normal local scans update prices only. EPS-only runs leave price data and the scan cursor unchanged. GitHub scheduled runs may start later than their scheduled time.

`data/earnings.json` stores the first successful latest reported fiscal quarter for each symbol, then appends subsequent quarters, including missed quarters since that baseline. Existing quarter values are never overwritten, including provider revisions, and removing a symbol from the Wishlist does not delete its archive. The current unreported quarter has no actual EPS yet. The Wishlist EPS section shows saved values, a trend line after two quarters, and the absolute quarter-to-quarter change, independently of the price range filter.

Commit `data/earnings.json` along with other generated data to publish it. The daily workflow includes this file automatically.

### EPS and PE chart

The Wishlist chart shows green quarterly EPS and blue trailing PE on separate labeled axes over weekly observation dates. PE uses the stored adjusted weekly price divided by four consecutive reported quarterly EPS values (TTM). Those four values come from the same EARNINGS response; older quarters are used for the TTM calculation without backfilling the displayed EPS archive. Missing prices, prices predating the report, incomplete TTM, and nonpositive trailing earnings produce an unavailable PE. Values retain the provider's EPS/share units, so ADR and currency conventions should match the price instrument.

Every EPS run appends an immutable weekly valuation snapshot (observation date, price date, price, quarter, EPS, EPS TTM and PE). A single observation is shown as a dot; lines develop with subsequent observations. Historical PE is never recalculated using today's price. Ordinary daily price runs do not add valuation observations.
