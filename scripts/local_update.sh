#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/.env.local"
RUN_FILE="$ROOT/data/.last-local-run"
TODAY=$(date -u +%F)

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing .env.local. Copy .env.local.example and add your Alpha Vantage API key."
  exit 1
fi

if [ -f "$RUN_FILE" ] && [ "$(cat "$RUN_FILE")" = "$TODAY" ]; then
  echo "The updater has already run today. Skipping to protect the daily quota."
  exit 0
fi

set -a
. "$ENV_FILE"
set +a

python3 "$ROOT/scripts/update_data.py"
printf '%s\n' "$TODAY" > "$RUN_FILE"
echo "Done. Refresh the local page to view results. Commit data/stocks.json and data/update-state.json to publish."
