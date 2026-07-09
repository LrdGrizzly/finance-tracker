"""Strategy Fit scoring — Phase 1.5: Selection layer only.

Scores a ticker's quote payload against the locked criteria:
- Graham defensive investor rules (the subset computable from yfinance info)
- Lynch PEG
- General value metrics (margin-of-safety proxies)

Each criterion returns: threshold, actual, pass/fail, deviation ratio,
and a plain-language note. Composite = weighted pass score 0-100.

Phase 2 will extend this to all five layers (Secular/Tactical/Timing/Risk)
once the signal engine and backtest exist.
"""


def _crit(name, threshold_text, actual, passed, deviation, note, weight=1.0):
    return {
        "name": name,
        "threshold": threshold_text,
        "actual": actual,
        "passed": passed,
        "deviation": deviation,   # how far from threshold, signed ratio; None if n/a
        "note": note,
        "weight": weight,
    }


def score_selection(q: dict) -> dict:
    """q = quote payload from fetcher.get_quote()."""
    criteria = []

    pe = q.get("trailingPE")
    if pe is not None:
        passed = pe <= 15
        criteria.append(_crit(
            "Graham: P/E ≤ 15", "≤ 15", round(pe, 2), passed,
            round((pe - 15) / 15, 2),
            "Price vs earnings. Graham's cap for a defensively priced stock." if passed
            else f"{round(pe / 15, 1)}× over Graham's cap — expensive by defensive standards.",
            weight=1.5,
        ))

    pb = q.get("priceToBook")
    if pb is not None:
        passed = pb <= 1.5
        criteria.append(_crit(
            "Graham: P/B ≤ 1.5", "≤ 1.5", round(pb, 2), passed,
            round((pb - 1.5) / 1.5, 2),
            "Price vs book value." if passed
            else "Above Graham's asset-backing threshold.",
            weight=1.0,
        ))

    # Graham combined rule: P/E × P/B ≤ 22.5 (allows trade-off between the two)
    if pe is not None and pb is not None:
        combo = pe * pb
        passed = combo <= 22.5
        criteria.append(_crit(
            "Graham combo: P/E × P/B ≤ 22.5", "≤ 22.5", round(combo, 1), passed,
            round((combo - 22.5) / 22.5, 2),
            "Combined valuation gate — allows higher P/E if P/B is low, and vice versa.",
            weight=1.5,
        ))

    cr = q.get("currentRatio")
    if cr is not None:
        passed = cr >= 2
        criteria.append(_crit(
            "Graham: current ratio ≥ 2", "≥ 2", round(cr, 2), passed,
            round((cr - 2) / 2, 2),
            "Short-term financial strength: current assets vs current liabilities.",
            weight=1.0,
        ))

    de = q.get("debtToEquity")
    if de is not None:
        # yfinance reports as percentage (e.g. 150 = 1.5x)
        passed = de <= 100
        criteria.append(_crit(
            "Debt/Equity ≤ 100%", "≤ 100%", round(de, 1), passed,
            round((de - 100) / 100, 2),
            "Leverage check — low debt is the margin of safety in bad years.",
            weight=1.0,
        ))

    peg = q.get("pegRatio")
    if peg is not None:
        passed = 0 < peg < 1
        criteria.append(_crit(
            "Lynch: PEG < 1", "< 1", round(peg, 2), passed,
            round(peg - 1, 2),
            "P/E relative to growth — fairly priced when PEG ≈ 1, cheap below." if passed
            else "Paying more per unit of growth than Lynch's fair-value line.",
            weight=1.5,
        ))

    roe = q.get("returnOnEquity")
    if roe is not None:
        passed = roe >= 0.10
        criteria.append(_crit(
            "Quality: ROE ≥ 10%", "≥ 10%", f"{round(roe * 100, 1)}%", passed,
            round((roe - 0.10) / 0.10, 2),
            "Business quality — return the company earns on shareholder capital.",
            weight=1.0,
        ))

    dy = q.get("dividendYield")
    if dy is not None:
        # yfinance returns this already as a percent (e.g. 5.15 = 5.15%)
        y = dy
        passed = y > 0
        criteria.append(_crit(
            "Dividend record (pays dividend)", "> 0", f"{round(y, 2)}%", passed,
            None,
            "Graham's defensive investor wants an uninterrupted dividend record.",
            weight=0.5,
        ))

    # 200-day MA position — cheap-zone proxy (reusable rule #10 from signal log)
    price, ma200 = q.get("price"), q.get("twoHundredDayAverage")
    if price is not None and ma200 not in (None, 0):
        below = price < ma200
        criteria.append(_crit(
            "Price vs 200d MA", "below = accumulation zone",
            f"{round((price / ma200 - 1) * 100, 1)}% vs MA", below,
            round(price / ma200 - 1, 2),
            "Below a rising long-term average = technically cheap zone (X-source rule #10). "
            "Above = paying up for momentum.",
            weight=0.5,
        ))

    evaluated = [c for c in criteria if c["passed"] is not None]
    if not evaluated:
        return {"score": None, "criteria": [], "note": "No fundamental data available (ETF or data gap)."}

    total_w = sum(c["weight"] for c in evaluated)
    passed_w = sum(c["weight"] for c in evaluated if c["passed"])
    score = round(100 * passed_w / total_w)

    return {
        "score": score,
        "layer": "SELECTION",
        "criteria": criteria,
        "evaluatedCount": len(evaluated),
        "note": (
            "Phase 1.5 — Selection layer only. Secular/Tactical/Timing/Risk layers "
            "join the composite in Phase 2 with the signal engine."
        ),
    }
