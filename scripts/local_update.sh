#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/.env.local"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing .env.local. Copy .env.local.example and add your Alpha Vantage API key."
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

python3 "$ROOT/scripts/update_data.py"
echo "Done. Refresh the local page to view results. Commit data/stocks.json and data/update-state.json to publish."
