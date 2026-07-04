#!/usr/bin/env python3
"""Rotate through Nasdaq-100 symbols and update weekly 200-week SMA data."""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SYMBOLS_FILE=ROOT/"data/nasdaq100.json"
OUTPUT_FILE=ROOT/"data/stocks.json"
STATE_FILE=ROOT/"data/update-state.json"
BLACKLIST_FILE=ROOT/"data/blacklist.json"
WATCHLIST_FILE=ROOT/"data/watchlist.json"
API_URL="https://www.alphavantage.co/query"
SCAN_ORDER_VERSION="watchlist-first-v2"

class InsufficientHistory(Exception):
    def __init__(self, weeks, latest):
        self.weeks=weeks
        self.latest=latest
        super().__init__(f"only {weeks} weekly points")

def load(path, fallback):
    try: return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError): return fallback

def resolve_symbols(values, valid_symbols, symbol_names):
    resolved=[]
    seen=set()
    for value in values:
        normalized=value.upper()
        symbol=normalized if normalized in valid_symbols else symbol_names.get(normalized)
        if symbol and symbol not in seen:
            resolved.append(symbol)
            seen.add(symbol)
    return resolved

def resolve_watchlist(values, valid_symbols, symbol_names):
    resolved=[]
    seen=set()
    for value in values:
        normalized=value.strip().upper()
        symbol=normalized if normalized in valid_symbols else symbol_names.get(normalized,normalized)
        if symbol and symbol not in seen:
            resolved.append(symbol)
            seen.add(symbol)
    return resolved

def build_scan_order(symbols, watchlist):
    watched=set(watchlist)
    by_symbol={symbol:name for symbol,name in symbols}
    return [(symbol,by_symbol.get(symbol,symbol)) for symbol in watchlist]+[
        (symbol,name) for symbol,name in symbols if symbol not in watched
    ]

def fetch(symbol, key):
    params=urllib.parse.urlencode({"function":"TIME_SERIES_WEEKLY_ADJUSTED","symbol":symbol,"apikey":key})
    req=urllib.request.Request(f"{API_URL}?{params}",headers={"User-Agent":"stock200w/1.0"})
    with urllib.request.urlopen(req,timeout=30) as response:
        payload=json.load(response)
    series=payload.get("Weekly Adjusted Time Series")
    if not series:
        message=payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "unknown API response"
        raise RuntimeError(message)
    points=sorted(series.items(),reverse=True)
    if len(points)<200:
        latest=points[0][0] if points else dt.date.today().isoformat()
        raise InsufficientHistory(len(points),latest)
    closes=[float(values["5. adjusted close"]) for _,values in points[:200]]
    return {"price":closes[0],"sma200":sum(closes)/200,"updated":points[0][0]}

def main():
    raw_keys=os.environ.get("ALPHA_VANTAGE_API_KEYS") or os.environ.get("ALPHA_VANTAGE_API_KEY","")
    keys=[key.strip() for key in raw_keys.split(",") if key.strip()]
    if not keys: raise SystemExit("ALPHA_VANTAGE_API_KEYS or ALPHA_VANTAGE_API_KEY is required")
    symbols=load(SYMBOLS_FILE,[])
    symbol_names={name.upper():symbol for symbol,name in symbols}
    valid_symbols={symbol for symbol,_ in symbols}
    blacklist=set(resolve_symbols(load(BLACKLIST_FILE,[]),valid_symbols,symbol_names))
    watchlist=resolve_watchlist(load(WATCHLIST_FILE,[]),valid_symbols,symbol_names)
    scan_order=build_scan_order(symbols,watchlist)
    old=load(OUTPUT_FILE,{"stocks":[]})
    cached={row["symbol"]:row for row in old.get("stocks",[])}
    insufficient={row["symbol"]:row for row in old.get("insufficient_history",[])}
    state=load(STATE_FILE,{"cursor":0})
    limit=min(int(os.environ.get("DAILY_LIMIT","25")),25)
    cursor=state.get("cursor",0)%len(scan_order) if state.get("scan_order")==SCAN_ORDER_VERSION else 0
    # Young listings are skipped until they can have 200 observations. Skips do
    # not consume one of the 25 daily request slots.
    batch=[]
    scanned=0
    today=dt.date.today()
    while len(batch)<limit and scanned<len(scan_order):
        symbol,name=scan_order[(cursor+scanned)%len(scan_order)]
        known=insufficient.get(symbol)
        scanned+=1
        if symbol not in blacklist and (not known or dt.date.fromisoformat(known["retry_after"])<=today):
            batch.append((symbol,name,scanned))
    failures=[]
    key_index=0
    key_requests=[0]*len(keys)
    progress_scanned=0
    quota_exhausted=False
    for index,(symbol,name,scan_position) in enumerate(batch):
        while key_index<len(keys):
            if key_requests[key_index]>=25:
                key_index+=1
                continue
            try:
                key_requests[key_index]+=1
                result=fetch(symbol,keys[key_index])
                result.update({"symbol":symbol,"name":name})
                result["distance"]=(result["price"]/result["sma200"]-1)*100
                cached[symbol]=result
                progress_scanned=scan_position
                print(f"updated {symbol}: {result['distance']:+.2f}% (key {key_index+1})")
                break
            except InsufficientHistory as exc:
                latest=dt.date.fromisoformat(exc.latest)
                retry_after=latest+dt.timedelta(weeks=200-exc.weeks)
                insufficient[symbol]={"symbol":symbol,"name":name,"weeks":exc.weeks,"checked_at":today.isoformat(),"retry_after":retry_after.isoformat()}
                cached.pop(symbol,None)
                progress_scanned=scan_position
                failures.append(f"{symbol}: {exc}; retry after {retry_after}")
                print(f"recorded {symbol}: {exc.weeks}/200 weeks, retry after {retry_after}")
                break
            except Exception as exc:
                message=str(exc)
                if "frequency" in message.lower() or "rate limit" in message.lower():
                    print(f"key {key_index+1} has reached its daily limit; switching key")
                    key_requests[key_index]=25
                    key_index+=1
                    continue
                failures.append(f"{symbol}: {exc}")
                progress_scanned=scan_position
                print(f"failed {symbol}: {exc}")
                break
        else:
            quota_exhausted=True
            print(f"all {len(keys)} key(s) have reached their daily limit; stopping before {symbol}")
            break
        if index<len(batch)-1: time.sleep(1)
    ordered=[cached[symbol] for symbol,_ in scan_order if symbol in cached and symbol not in blacklist]
    young=[insufficient[symbol] for symbol,_ in symbols if symbol in insufficient]
    OUTPUT_FILE.write_text(json.dumps({"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"stocks":ordered,"insufficient_history":young},indent=2)+"\n")
    STATE_FILE.write_text(json.dumps({"cursor":(cursor+progress_scanned)%len(scan_order),"scan_order":SCAN_ORDER_VERSION})+"\n")
    eligible_total=sum(symbol not in blacklist for symbol,_ in scan_order)
    print(f"coverage: {len(ordered)}/{eligible_total}")
    print(f"requests used by key: {key_requests}; planned stocks: {len(batch)}")
    if failures: print("failures: " + " | ".join(failures))

if __name__=="__main__": main()
