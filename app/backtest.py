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
# Calibration universe: Segreti Bancari + super-investor names from the
# Money Flow Research deep dives + EU quality/value names for balance.
EXTENDED_TICKERS = DEFAULT_TICKERS + [
    "AAPL", "NVDA", "META", "AMZN", "GOOGL", "TSM", "AVGO", "AMAT", "LRCX",
    "EQIX", "V", "QCOM", "MELI", "ISRG", "SPGI", "UNH", "LLY", "JPM",
    "XOM", "LIN", "MC.PA", "AIR.PA", "TTE.PA", "SAP.DE", "SIE.DE", "ALV.DE",
    "RACE.MI", "ISP.MI", "UCG.MI",
]
BENCHMARKS = ["SPY", "SWDA.MI"]

CAPE_AT_ENTRY = 36.5  # Shiller data, mid-2025 (hardcoded; multpl serves current only)

# Shiller CAPE at each calibration entry date (Shiller's published record,
# rounded — multpl.com only serves the current value)
CAPE_HISTORY = {
    "2022-06-30": 29.0, "2022-12-30": 28.3,
    "2023-06-30": 30.8, "2023-12-29": 32.6,
    "2024-06-28": 35.0, "2024-12-31": 37.9,
    "2025-06-30": 36.5,
}
CALIBRATION_DATES = ["2022-06-30", "2022-12-30", "2023-06-30",
                     "2023-12-29", "2024-06-28", "2025-06-30"]

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


_FUND_MEMO = {}


def _fundamentals(symbol):
    """Annual statement series for the PIT reconstruction, memoized per
    process. yfinance gives ~4 recent fiscal years; for US names SEC EDGAR
    extends the window to ~10y, which older entry dates need."""
    if symbol in _FUND_MEMO:
        return _FUND_MEMO[symbol]
    out = None
    try:
        t = yf.Ticker(symbol)
        fin, bal = t.financials, t.balance_sheet
        if fin is not None and not fin.empty and bal is not None and not bal.empty:
            out = {
                "ebit": _row(fin, "EBIT", "Operating Income"),
                "pretax": _row(fin, "Pretax Income"),
                "tax": _row(fin, "Tax Provision"),
                "net": _row(fin, "Net Income"),
                "revenue": _row(fin, "Total Revenue"),
                "gross": _row(fin, "Gross Profit"),
                "equity": _row(bal, "Stockholders Equity",
                               "Total Equity Gross Minority Interest"),
                "debt": _row(bal, "Total Debt"),
                "cash": _row(bal, "Cash And Cash Equivalents",
                             "Cash Cash Equivalents And Short Term Investments"),
                "shares": _row(bal, "Ordinary Shares Number", "Share Issued"),
            }
    except Exception:
        out = None
    # EDGAR depth for US names (extends 4y -> ~10y so 2022/2023 entries
    # still have pre-entry statements)
    if "." not in symbol:
        try:
            import edgar
            hist = edgar.get_annual_history(symbol)
            if hist and hist.get("series"):
                s = hist["series"]
                mapping = {"ebit": "ebit", "pretax": "pretax", "tax": "tax",
                           "net": "netincome", "revenue": "revenue",
                           "gross": "gross", "equity": "equity",
                           "debt": "debt", "cash": "cash", "shares": "shares"}
                out = out or {k: {} for k in mapping}
                for local, remote in mapping.items():
                    for y, v in (s.get(remote) or {}).items():
                        out[local].setdefault(str(y)[:4], float(v) if v is not None else None)
        except Exception:
            pass
    _FUND_MEMO[symbol] = out
    return out


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
        f = _fundamentals(symbol)
        if f:
            ebit, pretax, tax, net = f["ebit"], f["pretax"], f["tax"], f["net"]
            revenue, gross = f["revenue"], f["gross"]
            equity, debt, cash, shares = f["equity"], f["debt"], f["cash"], f["shares"]

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


def _eval_ticker(sym, entry_date, cape, horizon_bars=None):
    """One (ticker, entry date) reconstruction. horizon_bars fixes the exit
    N trading days after entry (calibration); None = latest close."""
    before, after = _bars_until(sym, entry_date)
    if len(before) < 60 or not after:
        return None, "insufficient history around entry date"
    entry_px = before[-1]["close"]
    exit_bar = after[min(horizon_bars - 1, len(after) - 1)] if horizon_bars else after[-1]
    exit_px = exit_bar["close"]
    ret = round((exit_px / entry_px - 1) * 100, 2)

    q = _point_in_time_quote(sym, before, entry_date[:4])
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
    if not any(v is not None for v in layers.values()):
        return None, "no layer scores computable"
    composite = _composite(layers, signals.WEIGHTS, cape)
    verdict, _ = signals.verdict_ladder(composite)
    return {
        "symbol": sym,
        "entryDate": before[-1]["date"],
        "entryPrice": round(entry_px, 2),
        "exitDate": exit_bar["date"],
        "exitPrice": round(exit_px, 2),
        "returnPct": ret,
        "horizonPartial": bool(horizon_bars) and len(after) < horizon_bars,
        "compositeAtEntry": composite,
        "verdictAtEntry": verdict,
        "layers": layers,
        "hit": _verdict_hit(verdict, ret),
    }, None


def _composite(layers, weights, cape):
    avail = {k: v for k, v in layers.items() if v is not None and k in weights}
    if not avail:
        return None
    total_w = sum(weights[k] for k in avail)
    raw = sum(v * weights[k] for k, v in avail.items()) / total_w
    return round(raw * signals.secular_multiplier(cape))


def run_backtest(tickers=None, entry_date="2025-06-30"):
    tickers = tickers or DEFAULT_TICKERS
    results, errors = [], []
    for sym in tickers:
        try:
            rec, err = _eval_ticker(sym, entry_date,
                                    CAPE_HISTORY.get(entry_date, CAPE_AT_ENTRY))
            if rec:
                results.append(rec)
            else:
                errors.append({"symbol": sym, "error": err})
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
        "capeAtEntry": CAPE_HISTORY.get(entry_date, CAPE_AT_ENTRY),
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


# ---------------- calibration grid ----------------

CAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""

# candidate configs: selection weight (rest split pro-rata among
# tactical/timing/risk at 25/25/50 of the remainder) × verdict thresholds
_SEL_WEIGHTS = [0.45, 0.55, 0.65]
_BUY_THRESHOLDS = [58, 62, 65, 70]
_HOLD_FLOORS = [40, 45, 50]


def _weights_for(sel):
    rest = 1.0 - sel
    return {"selection": sel, "tactical": rest * 0.25,
            "timing": rest * 0.25, "risk": rest * 0.50}


def run_calibration(tickers=None, entry_dates=None, horizon_bars=252):
    """Multi-date, multi-ticker sweep. Reconstructs layer scores once per
    (ticker, date), then grid-searches weights & verdict thresholds.
    Reports — does NOT auto-apply. Money Flow layer excluded (no
    point-in-time 13F reconstruction yet); composite renormalises without it,
    same as live behaviour for non-covered names."""
    tickers = tickers or EXTENDED_TICKERS
    entry_dates = entry_dates or CALIBRATION_DATES
    records, errors = [], []

    for entry_date in entry_dates:
        cape = CAPE_HISTORY.get(entry_date, CAPE_AT_ENTRY)
        for sym in tickers:
            try:
                rec, err = _eval_ticker(sym, entry_date, cape, horizon_bars)
                if rec:
                    rec["cape"] = cape
                    records.append(rec)
                else:
                    errors.append({"symbol": sym, "date": entry_date, "error": err})
            except Exception as e:
                errors.append({"symbol": sym, "date": entry_date, "error": str(e)})

    def bucket(v, buy_t, hold_f):
        if v is None:
            return None
        return "BUY" if v >= buy_t else ("HOLD" if v >= hold_f else "SELL")

    def hit(b, ret):
        if b == "BUY":
            return ret > 0
        if b == "HOLD":
            return ret > -10
        return ret < 0

    configs = []
    for sel in _SEL_WEIGHTS:
        w = _weights_for(sel)
        # composite per record for this weight set (thresholds don't affect it)
        comps = [(_composite(r["layers"], w, r["cape"]), r["returnPct"])
                 for r in records]
        for buy_t in _BUY_THRESHOLDS:
            for hold_f in _HOLD_FLOORS:
                stats = {"BUY": [], "HOLD": [], "SELL": []}
                hits = total = 0
                for comp, ret in comps:
                    b = bucket(comp, buy_t, hold_f)
                    if b is None:
                        continue
                    stats[b].append(ret)
                    total += 1
                    hits += 1 if hit(b, ret) else 0
                if not total:
                    continue
                avg = {k: (round(sum(v) / len(v), 2) if v else None)
                       for k, v in stats.items()}
                # monotonicity: BUY should out-return HOLD should out-return SELL
                mono = (avg["BUY"] is not None and avg["SELL"] is not None
                        and avg["BUY"] > (avg["HOLD"] or avg["BUY"] - 1)
                        and (avg["HOLD"] or avg["SELL"] + 1) > avg["SELL"])
                configs.append({
                    "selectionWeight": sel, "buyThreshold": buy_t,
                    "holdFloor": hold_f,
                    "hitRate": round(100 * hits / total),
                    "n": {k: len(v) for k, v in stats.items()},
                    "avgReturn": avg,
                    "buySellSpread": (round(avg["BUY"] - avg["SELL"], 2)
                                      if avg["BUY"] is not None and avg["SELL"] is not None
                                      else None),
                    "monotonic": mono,
                })

    # rank: monotonic first, then hit rate, then spread — and require the
    # BUY bucket to actually fire (>= 8 signals) to be considered actionable
    def rank_key(c):
        actionable = c["n"]["BUY"] >= 8
        return (c["monotonic"], actionable, c["hitRate"], c["buySellSpread"] or -999)
    configs.sort(key=rank_key, reverse=True)

    current = {"selectionWeight": signals.WEIGHTS["selection"],
               "buyThreshold": 65, "holdFloor": 45}

    payload = {
        "runAt": time.time(),
        "runAtHuman": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "entryDates": entry_dates,
        "horizonTradingDays": horizon_bars,
        "signalsEvaluated": len(records),
        "tickers": tickers,
        "topConfigs": configs[:10],
        "currentConfig": current,
        "errors": errors[:20],
        "errorCount": len(errors),
        "caveats": [
            f"{len(records)} signals across {len(entry_dates)} entry dates — indicative, not statistical proof",
            "Money Flow layer excluded (no point-in-time 13F reconstruction yet)",
            "Fixed 12-month horizon; last entry date is partially open",
            "Results REPORTED only — thresholds are not auto-applied (overfit guard)",
            "Selection reconstructed from pre-entry fiscal-year statements (EDGAR 10y for US, ~4y elsewhere)",
        ],
    }
    conn = get_conn()
    conn.executescript(CAL_SCHEMA)
    conn.execute("INSERT INTO calibration_runs (payload, created_at) VALUES (?, ?)",
                 (json.dumps(payload), time.time()))
    conn.commit()
    conn.close()
    return payload


def latest_calibration():
    conn = get_conn()
    conn.executescript(CAL_SCHEMA)
    row = conn.execute(
        "SELECT payload FROM calibration_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    return json.loads(row["payload"]) if row else None
