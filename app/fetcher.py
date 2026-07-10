"""Market data fetcher — yfinance + ECB FX, with SQLite caching.

Cache TTLs match how the data actually changes:
- quotes: 5 min while app open (Yahoo free data is ~15-min delayed anyway)
- history: 12 hours (daily bars, refreshed after market close)
- FX: 12 hours (ECB publishes one reference rate per business day)
"""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yfinance as yf

from db import cache_get, cache_put

QUOTE_TTL = 2 * 60  # near-live while app open; Yahoo free data is ~15min delayed anyway
HISTORY_TTL = 12 * 3600
FX_TTL = 12 * 3600

ECB_FX_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={}&quotesCount=8&newsCount=0"
SEARCH_TTL = 3600


def search_symbols(query: str) -> list:
    """Symbol lookup by name or ticker — Yahoo's free search endpoint."""
    key = f"__SEARCH_{query.lower().strip()}__"
    cached = cache_get("quotes", ["symbol"], [key], SEARCH_TTL)
    if cached:
        return json.loads(cached)

    url = YAHOO_SEARCH_URL.format(urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = [
        {
            "symbol": q.get("symbol"),
            "name": q.get("shortname") or q.get("longname") or "",
            "exchange": q.get("exchDisp") or q.get("exchange") or "",
            "type": q.get("quoteType") or "",
        }
        for q in data.get("quotes", [])
        if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "MUTUALFUND", "CRYPTOCURRENCY")
    ]
    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              [key, json.dumps(results), time.time()])
    return results


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
        "website": info.get("website"),
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


INTRADAY_TTL = 5 * 60


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> list:
    """OHLCV bars at any yfinance interval (1m…1wk).

    Intraday bars cache for 5 min; daily/weekly for 12h. Each row carries
    `t` (epoch seconds, chart-ready) and `date` (YYYY-MM-DD, backward compat).
    """
    symbol = symbol.upper().strip()
    key = f"{period}|{interval}"
    ttl = HISTORY_TTL if interval in ("1d", "1wk", "1mo") else INTRADAY_TTL
    cached = cache_get("history", ["symbol", "period"], [symbol, key], ttl)
    if cached:
        return json.loads(cached)

    t = yf.Ticker(symbol)
    df = t.history(period=period, interval=interval, auto_adjust=True)
    rows = [
        {
            "t": int(idx.timestamp()),
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 4),
            "high": round(float(r["High"]), 4),
            "low": round(float(r["Low"]), 4),
            "close": round(float(r["Close"]), 4),
            "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else 0,
        }
        for idx, r in df.iterrows()
        if r["Open"] == r["Open"]  # skip NaN bars
    ]
    cache_put(
        "history",
        ["symbol", "period", "payload", "fetched_at"],
        [symbol, key, json.dumps(rows), time.time()],
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
