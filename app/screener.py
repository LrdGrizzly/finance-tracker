"""Batch screening pipeline — Magic Formula + Graham + Lynch over the universe.

Runs as a background thread (started from the API), fetches each ticker's
fundamentals once, stores a compact screening row in SQLite. Progress is
queryable. Results feed the Suggestions tab, ranked.

Magic Formula (Phase 2 approximation, single-call-per-ticker):
  earnings yield ~ EBITDA / EV   (via enterpriseToEbitda, inverted)
  return on capital ~ returnOnAssets
  Greenblatt's exact formula needs EBIT + working capital from statements —
  that's 2 extra API calls per ticker across 500+ names. The approximation
  keeps the ranking spirit at 1/3 the fetch cost. Documented in methodology.
"""
import json
import threading
import time

import yfinance as yf

import universe
from db import get_conn

_state = {
    "running": False,
    "total": 0,
    "done": 0,
    "errors": 0,
    "startedAt": None,
    "finishedAt": None,
    "lastSymbol": None,
}
_lock = threading.Lock()

SCREEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS screen_results (
    symbol       TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    fetched_at   REAL NOT NULL
);
"""


def _screen_one(symbol: str) -> dict | None:
    t = yf.Ticker(symbol)
    info = t.info or {}
    price = info.get("regularMarketPrice")
    if price is None:
        return None

    ev_ebitda = info.get("enterpriseToEbitda")
    earnings_yield = round(1.0 / ev_ebitda, 4) if ev_ebitda and ev_ebitda > 0 else None
    roa = info.get("returnOnAssets")

    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    peg = info.get("pegRatio")
    eps = info.get("trailingEps")
    bvps = info.get("bookValue")

    graham_pass = 0
    graham_checks = 0
    if pe is not None:
        graham_checks += 1
        graham_pass += pe <= 15
    if pb is not None:
        graham_checks += 1
        graham_pass += pb <= 1.5
    if pe is not None and pb is not None:
        graham_checks += 1
        graham_pass += (pe * pb) <= 22.5
    cr = info.get("currentRatio")
    if cr is not None:
        graham_checks += 1
        graham_pass += cr >= 2

    mos = None
    if eps and bvps and eps > 0 and bvps > 0:
        gn = (22.5 * eps * bvps) ** 0.5
        mos = round((gn - price) / gn, 3)

    return {
        "symbol": symbol,
        "name": info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "currency": info.get("currency"),
        "price": price,
        "marketCap": info.get("marketCap"),
        "earningsYield": earnings_yield,
        "returnOnAssets": roa,
        "trailingPE": pe,
        "priceToBook": pb,
        "pegRatio": peg,
        "grahamPass": graham_pass,
        "grahamChecks": graham_checks,
        "marginOfSafety": mos,
    }


def _run(symbols):
    conn = get_conn()
    conn.executescript(SCREEN_SCHEMA)
    conn.close()

    for sym in symbols:
        with _lock:
            if not _state["running"]:
                break
            _state["lastSymbol"] = sym
        try:
            row = _screen_one(sym)
            if row:
                conn = get_conn()
                conn.executescript(SCREEN_SCHEMA)
                conn.execute(
                    "INSERT OR REPLACE INTO screen_results (symbol, payload, fetched_at) VALUES (?,?,?)",
                    (sym, json.dumps(row), time.time()),
                )
                conn.commit()
                conn.close()
        except Exception:
            with _lock:
                _state["errors"] += 1
        with _lock:
            _state["done"] += 1
        time.sleep(0.4)  # be polite to Yahoo — ~2.5 tickers/sec max

    with _lock:
        _state["running"] = False
        _state["finishedAt"] = time.time()


def start(limit: int | None = None) -> dict:
    with _lock:
        if _state["running"]:
            return dict(_state)
        uni = universe.get_universe()
        symbols = uni["symbols"][:limit] if limit else uni["symbols"]
        _state.update({
            "running": True, "total": len(symbols), "done": 0, "errors": 0,
            "startedAt": time.time(), "finishedAt": None, "lastSymbol": None,
            "sources": uni["sources"],
        })
    threading.Thread(target=_run, args=(symbols,), daemon=True).start()
    return dict(_state)


def status() -> dict:
    with _lock:
        return dict(_state)


def stop() -> dict:
    with _lock:
        _state["running"] = False
        return dict(_state)


def results(min_graham: int = 2, top: int = 50) -> list:
    """Ranked screening output — Magic Formula combined rank + Graham filter.

    Rank by earnings yield and ROA separately (Greenblatt's method), sum the
    two ranks, lowest combined rank wins. Filter: at least `min_graham`
    Graham checks passed OR positive margin of safety.
    """
    conn = get_conn()
    conn.executescript(SCREEN_SCHEMA)
    rows = [json.loads(r["payload"]) for r in
            conn.execute("SELECT payload FROM screen_results").fetchall()]
    conn.close()

    candidates = [
        r for r in rows
        if r.get("earningsYield") is not None and r.get("returnOnAssets") is not None
    ]
    # Greenblatt dual ranking
    by_ey = sorted(candidates, key=lambda r: r["earningsYield"], reverse=True)
    by_roa = sorted(candidates, key=lambda r: r["returnOnAssets"], reverse=True)
    ey_rank = {r["symbol"]: i for i, r in enumerate(by_ey)}
    roa_rank = {r["symbol"]: i for i, r in enumerate(by_roa)}
    for r in candidates:
        r["magicRank"] = ey_rank[r["symbol"]] + roa_rank[r["symbol"]]

    filtered = [
        r for r in candidates
        if (r.get("grahamPass", 0) >= min_graham)
        or (r.get("marginOfSafety") is not None and r["marginOfSafety"] > 0)
    ]
    filtered.sort(key=lambda r: r["magicRank"])
    return filtered[:top]
