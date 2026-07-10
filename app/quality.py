"""Quality-Compounder score — the user's primary investing lens.

Measures what the philosophy cares about, from actual financial statements
(annual, up to 4 years of history from yfinance):

- ROIC level and trend        (NOPAT / invested capital, target >= 15%)
- Gross & operating margins   (unit economics, moat proxy via stability)
- Reinvestment rate           (capex + retained earnings vs earnings)
- Revenue growth              (compounding runway evidence)
- Share count trend           (capital allocation: buybacks vs dilution)
- FCF conversion              (earnings quality)

Parallel to — not replacing — the Deep-Value score (strategy.py).
Statement fetches are cached 24h (they change quarterly at most).
"""
import json
import time

import yfinance as yf

from db import cache_get, cache_put

QUALITY_TTL = 24 * 3600
ROIC_TARGET = 0.15


def _safe_div(a, b):
    try:
        if a is None or b in (None, 0):
            return None
        return a / b
    except Exception:
        return None


def _row(df, *names):
    """First matching row from a statement DataFrame as {year: value}."""
    for name in names:
        if name in df.index:
            series = df.loc[name]
            return {str(k)[:4]: (None if v != v else float(v)) for k, v in series.items()}
    return {}


def _years_desc(*dicts):
    years = set()
    for d in dicts:
        years.update(k for k, v in d.items() if v is not None)
    return sorted(years, reverse=True)


def compute_quality(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    cached = cache_get("quotes", ["symbol"], [f"__Q_{symbol}__"], QUALITY_TTL)
    if cached:
        return json.loads(cached)

    t = yf.Ticker(symbol)
    fin = t.financials          # income statement, annual
    bal = t.balance_sheet
    cf = t.cashflow

    if fin is None or fin.empty or bal is None or bal.empty:
        result = {"score": None, "note": "No statement data (ETF, fund, or data gap)."}
        cache_put("quotes", ["symbol", "payload", "fetched_at"],
                  [f"__Q_{symbol}__", json.dumps(result), time.time()])
        return result

    ebit = _row(fin, "EBIT", "Operating Income")
    pretax = _row(fin, "Pretax Income")
    tax = _row(fin, "Tax Provision")
    revenue = _row(fin, "Total Revenue")
    gross = _row(fin, "Gross Profit")
    net_income = _row(fin, "Net Income")

    equity = _row(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    total_debt = _row(bal, "Total Debt")
    cash = _row(bal, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments")
    shares = _row(bal, "Ordinary Shares Number", "Share Issued")

    capex = _row(cf, "Capital Expenditure")
    op_cf = _row(cf, "Operating Cash Flow")

    years = _years_desc(ebit, equity)[:4]

    roic_series, gm_series, om_series = [], [], []
    for y in years:
        e = ebit.get(y)
        # effective tax rate for NOPAT; default 21% when unavailable
        tr = _safe_div(tax.get(y), pretax.get(y))
        tr = tr if tr is not None and 0 <= tr <= 0.5 else 0.21
        nopat = e * (1 - tr) if e is not None else None
        invested = None
        if equity.get(y) is not None:
            invested = equity[y] + (total_debt.get(y) or 0) - (cash.get(y) or 0)
        r = _safe_div(nopat, invested)
        if r is not None:
            roic_series.append({"year": y, "roic": round(r, 4)})
        g = _safe_div(gross.get(y), revenue.get(y))
        if g is not None:
            gm_series.append({"year": y, "gm": round(g, 4)})
        o = _safe_div(e, revenue.get(y))
        if o is not None:
            om_series.append({"year": y, "om": round(o, 4)})

    parts, notes = [], []

    # --- ROIC level + trend (the core test) ---
    if roic_series:
        latest = roic_series[0]["roic"]
        avg = sum(r["roic"] for r in roic_series) / len(roic_series)
        if avg >= ROIC_TARGET and latest >= ROIC_TARGET:
            parts.append(("ROIC", 90, 3.0))
            notes.append(f"ROIC {round(latest*100,1)}% latest, {round(avg*100,1)}% avg over {len(roic_series)}y — clears the 15% compounding bar")
        elif latest >= ROIC_TARGET:
            parts.append(("ROIC", 70, 3.0))
            notes.append(f"ROIC {round(latest*100,1)}% latest clears 15%, but multi-year avg {round(avg*100,1)}% below — durability unproven")
        elif latest >= 0.08:
            parts.append(("ROIC", 45, 3.0))
            notes.append(f"ROIC {round(latest*100,1)}% — decent business, not a compounder at the 15% bar")
        else:
            parts.append(("ROIC", 20, 3.0))
            notes.append(f"ROIC {round(latest*100,1)}% — capital earns little; philosophy mismatch")
        if len(roic_series) >= 3:
            rising = roic_series[0]["roic"] > roic_series[-1]["roic"]
            notes.append(f"ROIC trend over window: {'rising' if rising else 'falling'} "
                         f"({round(roic_series[-1]['roic']*100,1)}% → {round(roic_series[0]['roic']*100,1)}%)")

    # --- margin structure + stability (moat proxy) ---
    if gm_series:
        gm_latest = gm_series[0]["gm"]
        spread = max(g["gm"] for g in gm_series) - min(g["gm"] for g in gm_series)
        stable = spread < 0.05
        s = 80 if (gm_latest > 0.40 and stable) else (60 if gm_latest > 0.40 or stable else 40)
        parts.append(("Margins", s, 2.0))
        notes.append(f"Gross margin {round(gm_latest*100,1)}%, {len(gm_series)}y spread {round(spread*100,1)}pp — "
                     f"{'high and stable: pricing power evidence' if s == 80 else 'partial moat evidence' if s == 60 else 'thin/unstable — weak pricing power'}")
    if om_series and len(om_series) >= 2:
        expanding = om_series[0]["om"] > om_series[-1]["om"]
        notes.append(f"Operating margin {'expanding' if expanding else 'contracting'}: "
                     f"{round(om_series[-1]['om']*100,1)}% → {round(om_series[0]['om']*100,1)}%")

    # --- reinvestment rate (runway evidence) ---
    y0 = years[0] if years else None
    if y0 and net_income.get(y0) and capex.get(y0) is not None:
        reinvest = _safe_div(abs(capex[y0]), net_income[y0])
        if reinvest is not None and net_income[y0] > 0:
            s = 75 if 0.3 <= reinvest <= 1.2 else 50
            parts.append(("Reinvestment", s, 1.5))
            notes.append(f"Capex = {round(reinvest*100)}% of net income — "
                         f"{'meaningful reinvestment, runway being used' if s == 75 else 'low reinvestment (mature/returning cash) or outsized capex'}")

    # --- revenue growth (compounding evidence) ---
    rev_years = [y for y in years if revenue.get(y) is not None]
    if len(rev_years) >= 3:
        newest, oldest = revenue[rev_years[0]], revenue[rev_years[-1]]
        n = len(rev_years) - 1
        if oldest and oldest > 0:
            cagr = (newest / oldest) ** (1 / n) - 1
            s = 85 if cagr >= 0.10 else (60 if cagr >= 0.05 else 35)
            parts.append(("Growth", s, 1.5))
            notes.append(f"Revenue CAGR {round(cagr*100,1)}% over {n}y — "
                         f"{'genuine compounding' if s == 85 else 'moderate growth' if s == 60 else 'stagnant top line'}")

    # --- capital allocation: share count trend ---
    sh_years = [y for y in years if shares.get(y) is not None]
    if len(sh_years) >= 3:
        newest, oldest = shares[sh_years[0]], shares[sh_years[-1]]
        chg = _safe_div(newest - oldest, oldest)
        if chg is not None:
            if chg < -0.01:
                parts.append(("Capital allocation", 85, 2.0))
                notes.append(f"Share count shrank {round(-chg*100,1)}% over window — buybacks, owner-minded allocation")
            elif chg < 0.03:
                parts.append(("Capital allocation", 60, 2.0))
                notes.append("Share count roughly flat — no dilution, no aggressive returns")
            else:
                parts.append(("Capital allocation", 30, 2.0))
                notes.append(f"Share count grew {round(chg*100,1)}% — dilution working against shareholders")

    # --- FCF conversion (earnings quality) ---
    if y0 and op_cf.get(y0) and capex.get(y0) is not None and net_income.get(y0):
        fcf = op_cf[y0] - abs(capex[y0])
        conv = _safe_div(fcf, net_income[y0])
        if conv is not None and net_income[y0] > 0:
            s = 80 if conv >= 0.8 else (55 if conv >= 0.5 else 30)
            parts.append(("FCF conversion", s, 1.5))
            notes.append(f"FCF = {round(conv*100)}% of net income — "
                         f"{'earnings are real cash' if s == 80 else 'moderate conversion' if s == 55 else 'earnings not converting to cash — scrutinize accruals'}")

    if not parts:
        result = {"score": None, "note": "Insufficient statement data for quality scoring."}
    else:
        total_w = sum(w for _, _, w in parts)
        score = round(sum(s * w for _, s, w in parts) / total_w)
        result = {
            "score": score,
            "components": [{"name": n, "score": s, "weight": w} for n, s, w in parts],
            "notes": notes,
            "roicSeries": roic_series,
            "yearsCovered": years,
            "methodology": {
                "roic": "NOPAT (EBIT × (1 − effective tax)) / (equity + total debt − cash)",
                "source": "yfinance annual statements (up to 4 years)",
                "caveats": [
                    "4-year window — philosophy asks for longer durability than free data shows",
                    "Statement line-item names vary by company; missing rows skip that component",
                    "Moat is proxied by margin level/stability — qualitative moat judgment stays human",
                ],
            },
        }

    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              [f"__Q_{symbol}__", json.dumps(result), time.time()])
    return result
