"""Market data fetcher — yfinance + ECB FX, with SQLite caching.

Cache TTLs match how the data actually changes:
- quotes: 5 min while app open (Yahoo free data is ~15-min delayed anyway)
- history: 12 hours (daily bars, refreshed after market close)
- FX: 12 hours (ECB publishes one reference rate per business day)
"""
import json
import time
import urllib.request
import xml.etree.ElementTree as ET

import yfinance as yf

from db import cache_get, cache_put

QUOTE_TTL = 5 * 60
HISTORY_TTL = 12 * 3600
FX_TTL = 12 * 3600

ECB_FX_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def get_quote(symbol: str) -> dict:
    """Current quote + key fundamentals for one ticker."""
    symbol = symbol.upper().strip()
    cached = cache_get("quotes", ["symbol"], [symbol], QUOTE_TTL)
    if cached:
        return json.loads(cached)

    t = yf.Ticker(symbol)
    info = t.info or {}
    payload = {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "price": info.get("regularMarketPrice"),
        "previousClose": info.get("regularMarketPreviousClose"),
        "changePercent": info.get("regularMarketChangePercent"),
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "quoteType": info.get("quoteType"),
        "exchange": info.get("exchange"),
        "marketCap": info.get("marketCap"),
        # Selection-layer fundamentals (value investing core set)
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "priceToBook": info.get("priceToBook"),
        "pegRatio": info.get("pegRatio"),
        "freeCashflow": info.get("freeCashflow"),
        "returnOnEquity": info.get("returnOnEquity"),
        "debtToEquity": info.get("debtToEquity"),
        "currentRatio": info.get("currentRatio"),
        "trailingEps": info.get("trailingEps"),
        "bookValue": info.get("bookValue"),
        "enterpriseToEbitda": info.get("enterpriseToEbitda"),
        "returnOnAssets": info.get("returnOnAssets"),
        "earningsGrowth": info.get("earningsGrowth"),
        "dividendYield": info.get("dividendYield"),
        "fiftyDayAverage": info.get("fiftyDayAverage"),
        "twoHundredDayAverage": info.get("twoHundredDayAverage"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "fetchedAt": time.time(),
    }
    cache_put(
        "quotes",
        ["symbol", "payload", "fetched_at"],
        [symbol, json.dumps(payload), time.time()],
    )
    return payload


def get_history(symbol: str, period: str = "1y") -> list:
    """Daily OHLCV bars as list of dicts."""
    symbol = symbol.upper().strip()
    cached = cache_get("history", ["symbol", "period"], [symbol, period], HISTORY_TTL)
    if cached:
        return json.loads(cached)

    t = yf.Ticker(symbol)
    df = t.history(period=period, auto_adjust=True)
    rows = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 4),
            "high": round(float(r["High"]), 4),
            "low": round(float(r["Low"]), 4),
            "close": round(float(r["Close"]), 4),
            "volume": int(r["Volume"]),
        }
        for idx, r in df.iterrows()
    ]
    cache_put(
        "history",
        ["symbol", "period", "payload", "fetched_at"],
        [symbol, period, json.dumps(rows), time.time()],
    )
    return rows


def get_fx_rates() -> dict:
    """EUR reference rates from ECB. Returns {currency: 1 unit -> EUR}.

    Stored as a single JSON blob in the quotes table under the sentinel
    symbol __FX__ — one row, one TTL, same cache path as everything else.
    """
    cached = cache_get("quotes", ["symbol"], ["__FX__"], FX_TTL)
    if cached:
        return json.loads(cached)

    with urllib.request.urlopen(ECB_FX_URL, timeout=15) as resp:
        tree = ET.parse(resp)

    rates = {"EUR": 1.0}
    for cube in tree.getroot().iter("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube"):
        cur = cube.get("currency")
        rate = cube.get("rate")
        if cur and rate:
            # ECB publishes EUR -> currency; invert for currency -> EUR
            rates[cur] = 1.0 / float(rate)

    cache_put(
        "quotes",
        ["symbol", "payload", "fetched_at"],
        ["__FX__", json.dumps(rates), time.time()],
    )
    return rates
