#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/.env.local"

if [ -z "${ALPHA_VANTAGE_API_KEY:-}" ] && \
   [ -z "${ALPHA_VANTAGE_API_KEYS:-}" ] && \
   [ -z "${TIINGO_API_KEY:-}" ]; then
  if [ ! -f "$ENV_FILE" ]; then
    echo "Missing API key environment variables and .env.local."
    echo "Copy .env.local.example and add an Alpha Vantage or Tiingo API key."
    exit 1
  fi

  set -a
  . "$ENV_FILE"
  set +a
fi

if [ "$#" -eq 0 ] && [ -t 0 ]; then
  printf "Scan Wishlist first in this run? [y/N] "
  read -r RESCAN
  case "$RESCAN" in
    y|Y|yes|YES) set -- --rescan-wishlist ;;
  esac
fi

python3 "$ROOT/scripts/update_data.py" "$@"
echo "Done. Refresh the local page to view results. Commit data/stocks.json and data/update-state.json to publish."
