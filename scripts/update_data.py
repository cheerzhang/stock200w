#!/usr/bin/env python3
"""Rotate through wishlist and Nasdaq-100 weekly 200-week SMA data."""
import argparse
import datetime as dt
import json
import math
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
EARNINGS_FILE=ROOT/"data/earnings.json"
ALPHA_VANTAGE_API_URL="https://www.alphavantage.co/query"
TIINGO_API_URL="https://api.tiingo.com/tiingo/daily"
SCAN_ORDER_VERSION="nasdaq-excluding-wishlist-v5"

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

def build_scan_order(nasdaq, wishlist):
    names={symbol:name for symbol,name in nasdaq}
    seen=set()
    order=[]
    for group in ([(symbol,names.get(symbol,symbol)) for symbol in wishlist],nasdaq):
        for symbol,name in group:
            if symbol not in seen:
                order.append((symbol,name))
                seen.add(symbol)
    return order

def fetch_alpha_vantage(symbol, key, allow_short_history=False):
    params=urllib.parse.urlencode({"function":"TIME_SERIES_WEEKLY_ADJUSTED","symbol":symbol,"apikey":key})
    req=urllib.request.Request(f"{ALPHA_VANTAGE_API_URL}?{params}",headers={"User-Agent":"stock200w/1.0"})
    with urllib.request.urlopen(req,timeout=30) as response:
        payload=json.load(response)
    series=payload.get("Weekly Adjusted Time Series")
    if not series:
        message=payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "unknown API response"
        raise RuntimeError(message)
    points=sorted(series.items(),reverse=True)
    if len(points)<200 and not allow_short_history:
        latest=points[0][0] if points else dt.date.today().isoformat()
        raise InsufficientHistory(len(points),latest)
    if not points: raise RuntimeError("No weekly prices available")
    closes=[float(values["5. adjusted close"]) for _,values in points[:200]]
    return {"price":closes[0],"sma200":sum(closes)/len(closes),"weeks":len(closes),"updated":points[0][0]}

def fetch_earnings(symbol, key):
    params=urllib.parse.urlencode({"function":"EARNINGS","symbol":symbol,"apikey":key})
    req=urllib.request.Request(f"{ALPHA_VANTAGE_API_URL}?{params}",headers={"User-Agent":"stock200w/1.0"})
    with urllib.request.urlopen(req,timeout=30) as response:
        payload=json.load(response)
    if not isinstance(payload.get("quarterlyEarnings"),list) or not payload["quarterlyEarnings"]:
        raise RuntimeError(payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "No quarterly earnings available")
    rows=[]
    for row in payload["quarterlyEarnings"]:
        try:
            end=dt.date.fromisoformat(row["fiscalDateEnding"]).isoformat()
            eps=float(row["reportedEPS"])
            if not math.isfinite(eps): continue
        except (KeyError, ValueError, TypeError):
            continue
        rows.append({"fiscal_date_ending":end,"reported_date":row.get("reportedDate"),"eps":eps})
    if not rows: raise RuntimeError("No reported quarterly EPS available")
    rows.sort(key=lambda row:row["fiscal_date_ending"])
    for index,row in enumerate(rows):
        window=rows[max(0,index-3):index+1]
        dates=[dt.date.fromisoformat(item["fiscal_date_ending"]) for item in window]
        if len(window)==4 and all(60<=(b-a).days<=120 for a,b in zip(dates,dates[1:])):
            row["eps_ttm"]=sum(item["eps"] for item in window)
    return rows

def append_earnings(record, rows, today):
    # Start at the latest available quarter; never replace an archived EPS.
    history=record.setdefault("quarters",[])
    baseline=record.get("start_quarter") or (min(row["fiscal_date_ending"] for row in history) if history else rows[-1]["fiscal_date_ending"])
    record["start_quarter"]=baseline
    known={row["fiscal_date_ending"] for row in history}
    for row in rows:
        if row["fiscal_date_ending"] in known and "eps_ttm" in row:
            existing=next(item for item in history if item["fiscal_date_ending"]==row["fiscal_date_ending"])
            existing.setdefault("eps_ttm",row["eps_ttm"])
        if row["fiscal_date_ending"]>=baseline and row["fiscal_date_ending"] not in known:
            history.append({**row,"saved_at":today.isoformat()})
            known.add(row["fiscal_date_ending"])
    history.sort(key=lambda row:row["fiscal_date_ending"])


def append_valuation(record, stock, today):
    quarters=record.get("quarters",[])
    if not quarters: return False
    latest=max(quarters,key=lambda row:row["fiscal_date_ending"])
    price=stock.get("price")
    price_date=stock.get("updated")
    if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0 or not price_date: return False
    if price_date<(latest.get("reported_date") or latest["fiscal_date_ending"]): return False
    snapshots=record.setdefault("valuations",[])
    if any(row["observed_at"]==today.isoformat() for row in snapshots): return False
    ttm=latest.get("eps_ttm")
    pe=price/ttm if isinstance(ttm,(int,float)) and math.isfinite(ttm) and ttm>0 else None
    snapshots.append({"observed_at":today.isoformat(),"price":price,"price_date":price_date,
                      "fiscal_date_ending":latest["fiscal_date_ending"],"eps":latest["eps"],"eps_ttm":ttm,"pe":pe})
    snapshots.sort(key=lambda row:row["observed_at"])
    return True


def update_earnings(wishlist, blacklist, keys, limit, today):
    archive=load(EARNINGS_FILE,{"source":"Alpha Vantage EARNINGS","stocks":{}})
    records=archive["stocks"]
    requests=[0]*len(keys)
    used=0
    key_index=0
    budget=max(0,limit)
    eligible=[symbol for symbol in wishlist if symbol not in blacklist]
    eligible.sort(key=lambda symbol:records.get(symbol,{}).get("checked_at",""))
    for symbol in eligible:
        record=records.get(symbol,{})
        checked=record.get("checked_at")
        retry_days=1 if record.get("error") else 7
        if checked and record.get("quarters") and "eps_ttm" in record["quarters"][-1] and (today-dt.date.fromisoformat(checked)).days<retry_days: continue
        if used>=budget: break
        while key_index<len(keys) and used<budget:
            if requests[key_index]>=25:
                key_index+=1
                continue
            used+=1
            requests[key_index]+=1
            try:
                rows=fetch_earnings(symbol,keys[key_index])
                append_earnings(record,rows,today)
                record.pop("error",None)
                print(f"EPS updated {symbol}: {len(record['quarters'])} saved quarters")
            except Exception as exc:
                message=str(exc)
                if any(token in message.lower() for token in ("frequency","rate limit","25 requests","429")):
                    requests[key_index]=25
                    key_index+=1
                    print("Alpha Vantage EPS quota exhausted; preserving archive")
                    continue
                record["error"]=message
                print(f"EPS failed {symbol}: {message}")
            record["checked_at"]=today.isoformat()
            records[symbol]=record
            break
        if used<budget: time.sleep(1)
    prices={row["symbol"]:row for row in load(OUTPUT_FILE,{"stocks":[]}).get("stocks",[])}
    changed=False
    for symbol in eligible:
        if symbol in records:
            changed=append_valuation(records[symbol],prices.get(symbol,{}),today) or changed
    if used or changed:
        temporary=EARNINGS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(archive,indent=2,allow_nan=False)+"\n")
        temporary.replace(EARNINGS_FILE)
    return sum(requests),requests,key_index

def fetch_tiingo(symbol, key, allow_short_history=False):
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
    if len(points)<200 and not allow_short_history:
        latest=points[0]["date"][:10] if points else dt.date.today().isoformat()
        raise InsufficientHistory(len(points),latest)
    if not points: raise RuntimeError("No weekly prices available")
    closes=[float(row["adjClose"]) for row in points[:200]]
    return {"price":closes[0],"sma200":sum(closes)/len(closes),"weeks":len(closes),"updated":points[0]["date"][:10]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rescan-wishlist",action="store_true",help="scan wishlist first, then resume the saved rotation")
    parser.add_argument("--earnings-only",action="store_true",help="update Wishlist quarterly EPS only; leave prices and rotation unchanged")
    args=parser.parse_args()
    raw_keys=os.environ.get("ALPHA_VANTAGE_API_KEYS") or os.environ.get("ALPHA_VANTAGE_API_KEY","")
    keys=[key.strip() for key in raw_keys.split(",") if key.strip()]
    tiingo_key=os.environ.get("TIINGO_API_KEY","").strip()
    if not keys and not tiingo_key:
        raise SystemExit("an Alpha Vantage or Tiingo API key is required")
    nasdaq=load(SYMBOLS_FILE,[])
    symbols=build_scan_order(nasdaq,[])
    legacy_names=load(SP500_FILE,[])
    symbol_names={name.upper():symbol for symbol,name in [*legacy_names,*symbols]}
    valid_symbols={symbol for symbol,_ in symbols}
    watchlist=resolve_watchlist(load(WATCHLIST_FILE,[]),valid_symbols,symbol_names)
    blacklist=set(resolve_watchlist(load(BLACKLIST_FILE,[]),valid_symbols|set(watchlist),symbol_names))
    wishlist_set=set(watchlist)
    # Wishlist symbols are never part of the normal rotation. They are scanned
    # only when --rescan-wishlist is explicitly selected.
    scan_order=[row for row in build_scan_order(nasdaq,[]) if row[0] not in wishlist_set]
    names={symbol:name for symbol,name in [*legacy_names,*symbols]}
    old=load(OUTPUT_FILE,{"stocks":[]})
    cached={row["symbol"]:row for row in old.get("stocks",[])}
    insufficient={row["symbol"]:row for row in old.get("insufficient_history",[])}
    state=load(STATE_FILE,{})
    alpha_limit=min(int(os.environ.get("DAILY_LIMIT","25")),25*len(keys)) if keys else 0
    tiingo_limit=max(0,int(os.environ.get("TIINGO_DAILY_LIMIT","50"))) if tiingo_key else 0
    today=dt.date.today()
    if args.earnings_only:
        if not keys: raise SystemExit("an Alpha Vantage API key is required for EPS")
        used,_,_=update_earnings(watchlist,blacklist,keys,alpha_limit,today)
        print(f"EPS requests used/reserved: {used}/{alpha_limit}")
        return
    alpha_requests,key_requests,key_index=0,[0]*len(keys),0
    limit=max(0,alpha_limit-alpha_requests)+tiingo_limit
    order_index={symbol:index for index,(symbol,_) in enumerate(scan_order)}
    if state.get("next_symbol") in order_index:
        cursor=order_index[state["next_symbol"]]
    elif state.get("scan_order")==SCAN_ORDER_VERSION:
        cursor=state.get("cursor",0)%max(1,len(scan_order))
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
            if len(batch)>=limit: break
            if symbol not in blacklist:
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
                result=fetch_alpha_vantage(symbol,keys[key_index],allow_short_history=symbol in wishlist_set)
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
                result=fetch_tiingo(symbol,tiingo_key,allow_short_history=symbol in wishlist_set)
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
    storage_order=build_scan_order(nasdaq,watchlist)
    ordered=[cached[symbol] for symbol,_ in storage_order if symbol in cached and symbol not in blacklist]
    young=[insufficient[symbol] for symbol,_ in storage_order if symbol in insufficient]
    OUTPUT_FILE.write_text(json.dumps({"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"stocks":ordered,"insufficient_history":young},indent=2)+"\n")
    next_cursor=(cursor+progress_scanned)%max(1,len(scan_order))
    STATE_FILE.write_text(json.dumps({"cursor":next_cursor,"next_symbol":scan_order[next_cursor][0] if scan_order else None,"scan_order":SCAN_ORDER_VERSION})+"\n")
    eligible_total=sum(symbol not in blacklist for symbol,_ in storage_order)
    print(f"coverage: {len(ordered)}/{eligible_total}")
    print(f"requests used: Alpha Vantage {alpha_requests}/{alpha_limit} {key_requests}; Tiingo {tiingo_requests}/{tiingo_limit}; planned stocks: {len(batch)}")
    if failures: print("failures: " + " | ".join(failures))

if __name__=="__main__": main()
