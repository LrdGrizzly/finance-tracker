"""Screening universe — constituent lists from free, public sources.

- S&P 500: Wikipedia constituent table (free, community-maintained, reliable)
- Europe: EURO STOXX 50 from Wikipedia. Full STOXX 600 constituents have no
  free machine-readable source — flagged as a known limitation; EURO STOXX 50
  covers the large-cap EU sleeve until a better free source is found.
  (Maintenance page tracks this.)

Cached in SQLite for 7 days — constituents drift slowly.
"""
import json
import re
import time
import urllib.request

from db import cache_get, cache_put

UNIVERSE_TTL = 7 * 24 * 3600

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_STOXX50 = "https://en.wikipedia.org/wiki/EURO_STOXX_50"

UA = {"User-Agent": "Mozilla/5.0 (personal finance dashboard; local use)"}


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_sp500() -> list:
    cached = cache_get("quotes", ["symbol"], ["__UNIVERSE_SP500__"], UNIVERSE_TTL)
    if cached:
        return json.loads(cached)

    html = _fetch_html(WIKI_SP500)
    # constituent table: ticker cells are exchange-linked anchors with class "external text"
    symbols = re.findall(r'external text[^>]*>([A-Z][A-Z0-9.\-]{0,6})</a>', html)
    if len(symbols) < 400:
        # fallback — anchor to exchange quote pages
        symbols = re.findall(
            r'<a[^>]*href="https?://(?:www\.)?(?:nyse|nasdaq|cboe)\.com[^"]*"[^>]*>([A-Z][A-Z0-9.\-]{0,6})</a>',
            html,
        )
    symbols = sorted(set(s.replace(".", "-") for s in symbols))  # BRK.B -> BRK-B for Yahoo
    if len(symbols) < 400:
        raise RuntimeError(f"S&P 500 scrape looks wrong: {len(symbols)} symbols")

    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              ["__UNIVERSE_SP500__", json.dumps(symbols), time.time()])
    return symbols


def get_stoxx50() -> list:
    cached = cache_get("quotes", ["symbol"], ["__UNIVERSE_STOXX50__"], UNIVERSE_TTL)
    if cached:
        return json.loads(cached)

    html = _fetch_html(WIKI_STOXX50)
    # Wikipedia's EURO STOXX 50 table includes a Ticker column with exchange suffixes
    symbols = re.findall(r"<td[^>]*>([A-Z0-9]{1,6}\.[A-Z]{1,3})\s*</td>", html)
    symbols = sorted(set(symbols))
    if len(symbols) < 30:
        raise RuntimeError(f"EURO STOXX 50 scrape looks wrong: {len(symbols)} symbols")

    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              ["__UNIVERSE_STOXX50__", json.dumps(symbols), time.time()])
    return symbols


def get_universe() -> dict:
    """Full screening universe with per-source status."""
    result = {"symbols": [], "sources": {}}
    for name, fn in (("sp500", get_sp500), ("stoxx50", get_stoxx50)):
        try:
            syms = fn()
            result["symbols"].extend(syms)
            result["sources"][name] = {"count": len(syms), "ok": True}
        except Exception as e:
            result["sources"][name] = {"count": 0, "ok": False, "error": str(e)}
    result["symbols"] = sorted(set(result["symbols"]))
    return result
