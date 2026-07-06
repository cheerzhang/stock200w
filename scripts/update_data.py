#!/usr/bin/env python3
"""Rotate through wishlist, Nasdaq-100 and S&P 500 weekly 200-week SMA data."""
import argparse
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SYMBOLS_FILE=ROOT/"data/nasdaq100.json"
SP500_FILE=ROOT/"data/sp500.json"
OUTPUT_FILE=ROOT/"data/stocks.json"
STATE_FILE=ROOT/"data/update-state.json"
BLACKLIST_FILE=ROOT/"data/blacklist.json"
WATCHLIST_FILE=ROOT/"data/watchlist.json"
ALPHA_VANTAGE_API_URL="https://www.alphavantage.co/query"
TIINGO_API_URL="https://api.tiingo.com/tiingo/daily"
SCAN_ORDER_VERSION="nasdaq-sp500-excluding-wishlist-v4"

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

def build_scan_order(nasdaq, sp500, wishlist):
    names={symbol:name for symbol,name in [*sp500,*nasdaq]}
    seen=set()
    order=[]
    for group in ([(symbol,names.get(symbol,symbol)) for symbol in wishlist],nasdaq,sp500):
        for symbol,name in group:
            if symbol not in seen:
                order.append((symbol,name))
                seen.add(symbol)
    return order

def fetch_alpha_vantage(symbol, key):
    params=urllib.parse.urlencode({"function":"TIME_SERIES_WEEKLY_ADJUSTED","symbol":symbol,"apikey":key})
    req=urllib.request.Request(f"{ALPHA_VANTAGE_API_URL}?{params}",headers={"User-Agent":"stock200w/1.0"})
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

def fetch_tiingo(symbol, key):
    start_date=(dt.date.today()-dt.timedelta(days=366*6)).isoformat()
    params=urllib.parse.urlencode({"startDate":start_date,"resampleFreq":"weekly"})
    encoded_symbol=urllib.parse.quote(symbol,safe="")
    req=urllib.request.Request(
        f"{TIINGO_API_URL}/{encoded_symbol}/prices?{params}",
        headers={"Authorization":f"Token {key}","User-Agent":"stock200w/1.0"},
    )
    with urllib.request.urlopen(req,timeout=30) as response:
        payload=json.load(response)
    if not isinstance(payload,list):
        raise RuntimeError(payload.get("detail") or payload.get("message") or "unknown Tiingo API response")
    points=sorted(payload,key=lambda row:row["date"],reverse=True)
    if len(points)<200:
        latest=points[0]["date"][:10] if points else dt.date.today().isoformat()
        raise InsufficientHistory(len(points),latest)
    closes=[float(row["adjClose"]) for row in points[:200]]
    return {"price":closes[0],"sma200":sum(closes)/200,"updated":points[0]["date"][:10]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rescan-wishlist",action="store_true",help="scan wishlist first, then resume the saved rotation")
    args=parser.parse_args()
    raw_keys=os.environ.get("ALPHA_VANTAGE_API_KEYS") or os.environ.get("ALPHA_VANTAGE_API_KEY","")
    keys=[key.strip() for key in raw_keys.split(",") if key.strip()]
    tiingo_key=os.environ.get("TIINGO_API_KEY","").strip()
    if not keys and not tiingo_key:
        raise SystemExit("an Alpha Vantage or Tiingo API key is required")
    nasdaq=load(SYMBOLS_FILE,[])
    sp500=load(SP500_FILE,[])
    symbols=build_scan_order(nasdaq,sp500,[])
    symbol_names={name.upper():symbol for symbol,name in symbols}
    valid_symbols={symbol for symbol,_ in symbols}
    watchlist=resolve_watchlist(load(WATCHLIST_FILE,[]),valid_symbols,symbol_names)
    blacklist=set(resolve_watchlist(load(BLACKLIST_FILE,[]),valid_symbols|set(watchlist),symbol_names))
    wishlist_set=set(watchlist)
    # Wishlist symbols are never part of the normal rotation. They are scanned
    # only when --rescan-wishlist is explicitly selected.
    scan_order=[row for row in build_scan_order(nasdaq,sp500,[]) if row[0] not in wishlist_set]
    names={symbol:name for symbol,name in build_scan_order(nasdaq,sp500,[])}
    old=load(OUTPUT_FILE,{"stocks":[]})
    cached={row["symbol"]:row for row in old.get("stocks",[])}
    insufficient={row["symbol"]:row for row in old.get("insufficient_history",[])}
    state=load(STATE_FILE,{})
    alpha_limit=min(int(os.environ.get("DAILY_LIMIT","25")),25*len(keys)) if keys else 0
    tiingo_limit=max(0,int(os.environ.get("TIINGO_DAILY_LIMIT","50"))) if tiingo_key else 0
    limit=alpha_limit+tiingo_limit
    order_index={symbol:index for index,(symbol,_) in enumerate(scan_order)}
    if state.get("next_symbol") in order_index:
        cursor=order_index[state["next_symbol"]]
    elif state.get("scan_order")==SCAN_ORDER_VERSION:
        cursor=state.get("cursor",0)%len(scan_order)
    else:
        # On a queue migration, continue at the first symbol with no stored
        # result instead of throwing away progress and restarting at index 0.
        cursor=next((index for index,(symbol,_) in enumerate(scan_order)
                     if symbol not in cached and symbol not in insufficient),0)
    # Young listings are skipped until they can have 200 observations. Skips do
    # not consume one of the 25 daily request slots.
    batch=[]
    batch_symbols=set()
    scanned=0
    today=dt.date.today()
    # Finish initial coverage before refreshing cached symbols. Existing rows
    # are skipped without using quota until every eligible symbol has either a
    # market-data row or an insufficient-history record.
    coverage_incomplete=any(symbol not in cached and symbol not in insufficient and symbol not in blacklist
                            for symbol,_ in scan_order)
    # An explicit wishlist refresh is extra work ahead of the saved plan. It
    # consumes request quota but never rewinds the normal rotation cursor.
    if args.rescan_wishlist:
        for symbol in watchlist:
            known=insufficient.get(symbol)
            if len(batch)>=limit: break
            if symbol not in blacklist and (not known or dt.date.fromisoformat(known["retry_after"])<=today):
                batch.append((symbol,names.get(symbol,symbol),0))
                batch_symbols.add(symbol)
    while len(batch)<limit and scanned<len(scan_order):
        symbol,name=scan_order[(cursor+scanned)%len(scan_order)]
        known=insufficient.get(symbol)
        scanned+=1
        already_recorded=symbol in cached or known is not None
        if coverage_incomplete and already_recorded:
            continue
        if symbol not in batch_symbols and symbol not in blacklist and (not known or dt.date.fromisoformat(known["retry_after"])<=today):
            batch.append((symbol,name,scanned))
            batch_symbols.add(symbol)
    failures=[]
    key_index=0
    key_requests=[0]*len(keys)
    alpha_requests=0
    tiingo_requests=0
    progress_scanned=0
    quota_exhausted=False
    for index,(symbol,name,scan_position) in enumerate(batch):
        result=None
        source=None
        provider_errors=[]
        insufficient_error=None
        while key_index<len(keys) and alpha_requests<alpha_limit:
            if key_requests[key_index]>=25:
                key_index+=1
                continue
            try:
                key_requests[key_index]+=1
                alpha_requests+=1
                result=fetch_alpha_vantage(symbol,keys[key_index])
                source=f"Alpha Vantage key {key_index+1}"
                break
            except InsufficientHistory as exc:
                insufficient_error=exc
                break
            except Exception as exc:
                message=str(exc)
                if "frequency" in message.lower() or "rate limit" in message.lower():
                    print(f"key {key_index+1} has reached its daily limit; switching key")
                    key_requests[key_index]=25
                    key_index+=1
                    continue
                provider_errors.append(f"Alpha Vantage: {exc}")
                break
        if result is None and insufficient_error is None and tiingo_key and tiingo_requests<tiingo_limit:
            try:
                tiingo_requests+=1
                result=fetch_tiingo(symbol,tiingo_key)
                source="Tiingo"
            except InsufficientHistory as exc:
                insufficient_error=exc
            except Exception as exc:
                provider_errors.append(f"Tiingo: {exc}")
                if "rate limit" in str(exc).lower() or "429" in str(exc):
                    tiingo_requests=tiingo_limit
        if result is not None:
            result.update({"symbol":symbol,"name":name,"source":source})
            result["distance"]=(result["price"]/result["sma200"]-1)*100
            cached[symbol]=result
            insufficient.pop(symbol,None)
            progress_scanned=max(progress_scanned,scan_position)
            print(f"updated {symbol}: {result['distance']:+.2f}% ({source})")
        elif insufficient_error is not None:
            latest=dt.date.fromisoformat(insufficient_error.latest)
            retry_after=latest+dt.timedelta(weeks=200-insufficient_error.weeks)
            insufficient[symbol]={"symbol":symbol,"name":name,"weeks":insufficient_error.weeks,"checked_at":today.isoformat(),"retry_after":retry_after.isoformat()}
            cached.pop(symbol,None)
            progress_scanned=max(progress_scanned,scan_position)
            failures.append(f"{symbol}: {insufficient_error}; retry after {retry_after}")
            print(f"recorded {symbol}: {insufficient_error.weeks}/200 weeks, retry after {retry_after}")
        elif (key_index>=len(keys) or alpha_requests>=alpha_limit) and (not tiingo_key or tiingo_requests>=tiingo_limit) and not provider_errors:
            quota_exhausted=True
            print(f"all provider quotas are exhausted; stopping before {symbol}")
            break
        else:
            message=" | ".join(provider_errors) or "no market-data provider available"
            failures.append(f"{symbol}: {message}")
            progress_scanned=max(progress_scanned,scan_position)
            print(f"failed {symbol}: {message}")
        if index<len(batch)-1: time.sleep(1)
    storage_order=build_scan_order(nasdaq,sp500,watchlist)
    ordered=[cached[symbol] for symbol,_ in storage_order if symbol in cached and symbol not in blacklist]
    young=[insufficient[symbol] for symbol,_ in storage_order if symbol in insufficient]
    OUTPUT_FILE.write_text(json.dumps({"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"stocks":ordered,"insufficient_history":young},indent=2)+"\n")
    next_cursor=(cursor+progress_scanned)%len(scan_order)
    STATE_FILE.write_text(json.dumps({"cursor":next_cursor,"next_symbol":scan_order[next_cursor][0],"scan_order":SCAN_ORDER_VERSION})+"\n")
    eligible_total=sum(symbol not in blacklist for symbol,_ in storage_order)
    print(f"coverage: {len(ordered)}/{eligible_total}")
    print(f"requests used: Alpha Vantage {alpha_requests}/{alpha_limit} {key_requests}; Tiingo {tiingo_requests}/{tiingo_limit}; planned stocks: {len(batch)}")
    if failures: print("failures: " + " | ".join(failures))

if __name__=="__main__": main()
