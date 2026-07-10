"""SEC EDGAR fundamentals — extends US-name statement history to ~10 years.

Free, official, no key. SEC fair-access policy requires a descriptive
User-Agent with contact info. Two endpoints:
- ticker -> CIK map:  https://www.sec.gov/files/company_tickers.json
- XBRL company facts: https://data.sec.gov/api/xbrl/companyfacts/CIK{10d}.json

Extracts annual (10-K, form-level FY) us-gaap series needed by the quality
lens: EBIT/operating income, pretax income, tax, revenue, gross profit,
equity, debt, cash, shares. Non-US names return None (EDGAR is US-only).
"""
import json
import time
import urllib.request

from db import cache_get, cache_put

UA = {"User-Agent": "PersonalFinanceDashboard/1.0 (miragoli.a@gmail.com)"}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

MAP_TTL = 7 * 24 * 3600
FACTS_TTL = 24 * 3600

# us-gaap concept preferences per series (first hit wins)
CONCEPTS = {
    "ebit": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "SalesRevenueNet"],
    "gross": ["GrossProfit"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "ltdebt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "stdebt": ["LongTermDebtCurrent", "DebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "shares": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    "netincome": ["NetIncomeLoss"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "opcf": ["NetCashProvidedByUsedInOperatingActivities"],
}


def _fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_cik(symbol: str):
    """CIK for a US-listed ticker, or None."""
    symbol = symbol.upper().strip()
    cached = cache_get("quotes", ["symbol"], ["__EDGAR_CIKMAP__"], MAP_TTL)
    if cached:
        mapping = json.loads(cached)
    else:
        raw = _fetch_json(TICKER_MAP_URL)
        mapping = {v["ticker"].upper(): v["cik_str"] for v in raw.values()}
        cache_put("quotes", ["symbol", "payload", "fetched_at"],
                  ["__EDGAR_CIKMAP__", json.dumps(mapping), time.time()])
    return mapping.get(symbol.replace("-", ""))  # BRK-B -> BRKB per SEC map


def _annual_series(facts, concepts):
    """{fiscal_year: value} from 10-K annual facts, latest filing wins."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        node = gaap.get(concept)
        if not node:
            continue
        out = {}
        for unit_vals in node.get("units", {}).values():
            for v in unit_vals:
                # annual figures: 10-K frames with fiscal-year designation
                if v.get("form") == "10-K" and v.get("fp") == "FY" and v.get("fy"):
                    fy = str(v["fy"])
                    # keep the most recently filed value for that year
                    if fy not in out or v.get("filed", "") > out[fy][1]:
                        out[fy] = (v["val"], v.get("filed", ""))
        if out:
            return {y: val for y, (val, _) in out.items()}
    return {}


def get_annual_history(symbol: str):
    """Full annual fundamentals history for a US name, or None if not on EDGAR."""
    symbol = symbol.upper().strip()
    key = f"__EDGAR_{symbol}__"
    cached = cache_get("quotes", ["symbol"], [key], FACTS_TTL)
    if cached:
        data = json.loads(cached)
        return data if data else None

    cik = get_cik(symbol)
    if cik is None:
        cache_put("quotes", ["symbol", "payload", "fetched_at"],
                  [key, json.dumps(None), time.time()])
        return None

    facts = _fetch_json(FACTS_URL.format(cik=int(cik)))
    series = {name: _annual_series(facts, concepts) for name, concepts in CONCEPTS.items()}
    # combined total debt
    debt = {}
    for y in set(series["ltdebt"]) | set(series["stdebt"]):
        debt[y] = (series["ltdebt"].get(y) or 0) + (series["stdebt"].get(y) or 0)
    series["debt"] = debt

    years = sorted(series["equity"].keys(), reverse=True)
    result = {"symbol": symbol, "cik": cik, "years": years, "series": series,
              "source": "SEC EDGAR (10-K XBRL)"}
    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              [key, json.dumps(result), time.time()])
    return result
