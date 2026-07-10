"""Backtest engine — Model Health calibration run.

Simulates buying the Segreti Bancari single-stock universe at a past entry
date, reconstructs what the signal engine would have said THEN (point-in-time
where possible), and compares verdicts against realized returns.

Point-in-time honesty:
- Tactical/Timing/Risk: exact — computed from price bars up to entry date.
- Selection: approximate — annual statements with fiscal years <= entry year
  (published before entry), deep-value ratios from entry price / FY-prior EPS
  and book value. Slightly different from what Yahoo displayed live that day.
- Secular: CAPE at entry hardcoded from the Shiller record (~36.5 mid-2025);
  multpl.com only serves the current value.

Hit rules (documented in output):
- STRONG BUY / BUY  -> hit if return > 0
- HOLD              -> hit if return > -10% (capital preserved)
- SELL / STRONG SELL-> hit if return < 0
"""
import json
import time
from datetime import datetime

import yfinance as yf

import fetcher
import signals
from db import get_conn

# Segreti Bancari single-stock universe (Investo Stocks + Conservativo).
# ETFs excluded: quality/deep-value lenses don't apply to funds and EU
# share-class ISIN -> Yahoo mapping is unreliable.
DEFAULT_TICKERS = [
    "WMT", "MSFT", "OR.PA", "CSCO", "SAN.PA", "CAT", "ABT",
    "ASML", "MA", "CRM", "GOOG", "ENEL.MI", "MARR.MI",
]
BENCHMARKS = ["SPY", "SWDA.MI"]

CAPE_AT_ENTRY = 36.5  # Shiller data, mid-2025 (hardcoded; multpl serves current only)

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


def _row(df, *names):
    for name in names:
        if name in df.index:
            return {str(k)[:4]: (None if v != v else float(v)) for k, v in df.loc[name].items()}
    return {}


def _bars_until(symbol, entry_date):
    """Daily bars: full 5y fetch, split at entry date."""
    rows = fetcher.get_history(symbol, "5y", "1d")
    before = [r for r in rows if r["date"] <= entry_date]
    after = [r for r in rows if r["date"] > entry_date]
    return before, after


def _point_in_time_quote(symbol, before, entry_year):
    """Synthetic quote dict as of entry, for the technical/risk layers."""
    closes = [r["close"] for r in before]
    price = closes[-1]
    last252 = closes[-252:] if len(closes) >= 252 else closes
    q = {
        "symbol": symbol,
        "price": price,
        "fiftyDayAverage": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
        "twoHundredDayAverage": sum(closes[-200:]) / 200 if len(closes) >= 200 else None,
        "fiftyTwoWeekHigh": max(last252),
        "fiftyTwoWeekLow": min(last252),
    }

    # statement-based fundamentals with fiscal years <= entry_year - 1
    try:
        t = yf.Ticker(symbol)
        fin, bal = t.financials, t.balance_sheet
        if fin is not None and not fin.empty and bal is not None and not bal.empty:
            ebit = _row(fin, "EBIT", "Operating Income")
            pretax = _row(fin, "Pretax Income")
            tax = _row(fin, "Tax Provision")
            net = _row(fin, "Net Income")
            revenue = _row(fin, "Total Revenue")
            gross = _row(fin, "Gross Profit")
            equity = _row(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
            debt = _row(bal, "Total Debt")
            cash = _row(bal, "Cash And Cash Equivalents",
                        "Cash Cash Equivalents And Short Term Investments")
            shares = _row(bal, "Ordinary Shares Number", "Share Issued")

            years = sorted({y for y in equity if equity[y] is not None
                            and int(y) < int(entry_year)}, reverse=True)
            q["_years"] = years
            if years:
                y0 = years[0]
                sh = shares.get(y0)
                if net.get(y0) and sh:
                    q["trailingEps"] = net[y0] / sh
                if equity.get(y0) and sh:
                    q["bookValue"] = equity[y0] / sh
                if equity.get(y0) and debt.get(y0) is not None and equity[y0] > 0:
                    q["debtToEquity"] = 100 * debt[y0] / equity[y0]

                # mini quality score on pre-entry years (ROIC avg, margins, growth)
                parts = []
                roics = []
                for y in years[:4]:
                    e = ebit.get(y)
                    tr = None
                    if tax.get(y) is not None and pretax.get(y):
                        tr = tax[y] / pretax[y]
                    tr = tr if tr is not None and 0 <= tr <= 0.5 else 0.21
                    inv = (equity.get(y) or 0) + (debt.get(y) or 0) - (cash.get(y) or 0)
                    if e is not None and inv > 0:
                        roics.append(e * (1 - tr) / inv)
                if roics:
                    avg = sum(roics) / len(roics)
                    parts.append(90 if avg >= 0.15 else (55 if avg >= 0.08 else 25))
                if gross.get(y0) and revenue.get(y0):
                    gm = gross[y0] / revenue[y0]
                    parts.append(80 if gm > 0.40 else 45)
                rev_years = [y for y in years[:4] if revenue.get(y)]
                if len(rev_years) >= 3:
                    newest, oldest = revenue[rev_years[0]], revenue[rev_years[-1]]
                    if oldest and oldest > 0:
                        cagr = (newest / oldest) ** (1 / (len(rev_years) - 1)) - 1
                        parts.append(85 if cagr >= 0.10 else (60 if cagr >= 0.05 else 35))
                if parts:
                    q["_qualityPIT"] = round(sum(parts) / len(parts))

                # deep-value at entry price
                dv_parts = []
                eps, bvps = q.get("trailingEps"), q.get("bookValue")
                if eps and eps > 0:
                    pe = price / eps
                    dv_parts.append(90 if pe <= 15 else (50 if pe <= 25 else 20))
                if bvps and bvps > 0:
                    pb = price / bvps
                    dv_parts.append(90 if pb <= 1.5 else (50 if pb <= 4 else 20))
                if eps and bvps and eps > 0 and bvps > 0:
                    gn = (22.5 * eps * bvps) ** 0.5
                    mos = (gn - price) / gn
                    dv_parts.append(90 if mos >= 0.2 else (60 if mos > 0 else 25))
                if dv_parts:
                    q["_deepValuePIT"] = round(sum(dv_parts) / len(dv_parts))
    except Exception:
        pass
    return q


def _verdict_hit(verdict, ret):
    if verdict in ("STRONG BUY", "BUY"):
        return ret > 0
    if verdict == "HOLD":
        return ret > -10
    if verdict in ("SELL", "STRONG SELL", "BLOCKED"):
        return ret < 0
    return None


def run_backtest(tickers=None, entry_date="2025-06-30"):
    tickers = tickers or DEFAULT_TICKERS
    entry_year = entry_date[:4]
    results, errors = [], []

    for sym in tickers:
        try:
            before, after = _bars_until(sym, entry_date)
            if len(before) < 60 or not after:
                errors.append({"symbol": sym, "error": "insufficient history around entry date"})
                continue
            entry_px = before[-1]["close"]
            exit_px = after[-1]["close"]
            ret = round((exit_px / entry_px - 1) * 100, 2)

            q = _point_in_time_quote(sym, before, entry_year)
            closes = [r["close"] for r in before]

            tactical = signals.score_tactical(q, closes)
            timing = signals.score_timing(q, closes)
            risk = signals.score_risk(q, closes)

            qs, dv = q.get("_qualityPIT"), q.get("_deepValuePIT")
            if qs is not None and dv is not None:
                selection = round(0.65 * qs + 0.35 * dv)
            else:
                selection = qs if qs is not None else dv

            layers = {"selection": selection, "tactical": tactical.get("score"),
                      "timing": timing.get("score"), "risk": risk.get("score")}
            avail = {k: v for k, v in layers.items() if v is not None}
            if not avail:
                errors.append({"symbol": sym, "error": "no layer scores computable"})
                continue
            total_w = sum(signals.WEIGHTS[k] for k in avail)
            raw = sum(v * signals.WEIGHTS[k] for k, v in avail.items()) / total_w
            mult = signals.secular_multiplier(CAPE_AT_ENTRY)
            composite = round(raw * mult)
            verdict, strength = signals.verdict_ladder(composite)

            results.append({
                "symbol": sym,
                "entryDate": before[-1]["date"],
                "entryPrice": round(entry_px, 2),
                "exitDate": after[-1]["date"],
                "exitPrice": round(exit_px, 2),
                "returnPct": ret,
                "compositeAtEntry": composite,
                "verdictAtEntry": verdict,
                "layers": layers,
                "hit": _verdict_hit(verdict, ret),
            })
        except Exception as e:
            errors.append({"symbol": sym, "error": str(e)})

    # benchmarks
    benchmarks = []
    for sym in BENCHMARKS:
        try:
            before, after = _bars_until(sym, entry_date)
            if before and after:
                benchmarks.append({
                    "symbol": sym,
                    "returnPct": round((after[-1]["close"] / before[-1]["close"] - 1) * 100, 2),
                })
        except Exception:
            pass

    # aggregate per verdict bucket
    buckets = {}
    for r in results:
        b = buckets.setdefault(r["verdictAtEntry"], {"n": 0, "hits": 0, "returns": []})
        b["n"] += 1
        b["hits"] += 1 if r["hit"] else 0
        b["returns"].append(r["returnPct"])
    bucket_stats = [
        {
            "verdict": v,
            "count": b["n"],
            "hitRate": round(100 * b["hits"] / b["n"]) if b["n"] else None,
            "avgReturn": round(sum(b["returns"]) / len(b["returns"]), 2),
        }
        for v, b in buckets.items()
    ]
    scored = [r for r in results if r["hit"] is not None]
    overall = round(100 * sum(1 for r in scored if r["hit"]) / len(scored)) if scored else None

    payload = {
        "entryDate": entry_date,
        "runAt": time.time(),
        "runAtHuman": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "capeAtEntry": CAPE_AT_ENTRY,
        "results": sorted(results, key=lambda r: -r["returnPct"]),
        "benchmarks": benchmarks,
        "bucketStats": bucket_stats,
        "overallHitRate": overall,
        "target": 70,
        "tickersTested": len(results),
        "errors": errors,
        "caveats": [
            "Selection layer reconstructed from annual statements (fiscal years before entry) — differs slightly from live data at the time",
            f"CAPE at entry hardcoded to {CAPE_AT_ENTRY} (Shiller record); multpl.com serves current value only",
            "One entry date, one year, ~13 names — a calibration sample, not statistical proof",
            "ETFs from the newsletters excluded — quality/value lenses don't apply to funds",
            "Hit rules: BUY-ish needs return>0, HOLD needs >-10%, SELL-ish needs <0",
        ],
    }

    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO backtest_runs (payload, created_at) VALUES (?, ?)",
                 (json.dumps(payload), time.time()))
    conn.commit()
    conn.close()
    return payload


def latest_run():
    conn = get_conn()
    conn.executescript(SCHEMA)
    row = conn.execute(
        "SELECT payload FROM backtest_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    return json.loads(row["payload"]) if row else None
