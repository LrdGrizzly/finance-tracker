"""Money Flow lens — what tracked super-investors are actually doing.

Source: SEC EDGAR 13F-HR filings (free, official, quarterly, ~45d lag).
Tracks six managers whose strategies the user studies (Money Flow Research):
Berkshire (Abel), Duquesne (Druckenmiller), Coatue (Laffont),
Tiger Global (Coleman), Oaktree (Marks), Tudor (Paul Tudor Jones).

For each ticker: is the smart money accumulating or distributing?
Compares each manager's latest 13F vs the prior one — new buy / add /
hold / reduce / exit — weighted by how big the position is for that
manager. Put positions count as bearish, calls as mildly bullish.

Honest limits (surfaced in the payload):
- 13Fs lag ~45 days and only cover US-listed long positions (incl. ADRs).
- Shorts, bonds, and non-US lines are invisible.
- Absence of a name is NOT bearish — the layer returns None, and the
  composite renormalises without it.
"""
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from db import cache_get, cache_put

UA = {"User-Agent": "PersonalFinanceDashboard/1.0 (miragoli.a@gmail.com)"}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{file}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

HOLDINGS_TTL = 7 * 24 * 3600  # 13Fs are quarterly; weekly refresh is plenty

MANAGERS = {
    1067983: {"name": "Berkshire Hathaway (Abel)", "style": "Quality value, decade horizon"},
    1536411: {"name": "Duquesne (Druckenmiller)", "style": "Macro cycles, liquidity"},
    1135730: {"name": "Coatue (Laffont)", "style": "Tech secular trends"},
    1167483: {"name": "Tiger Global (Coleman)", "style": "Tech growth, category leaders"},
    949509:  {"name": "Oaktree (Marks)", "style": "Cycle psychology, credit risk"},
    923093:  {"name": "Tudor (Paul Tudor Jones)", "style": "Macro, defined-risk options"},
}

_SUFFIX = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|PLC|LTD|LIMITED|SA|NV|SE|AG|"
    r"HOLDINGS?|HLDGS?|GROUP|GRP|CLASS|CL|COM|COMMON|STOCK|SHS|SHARES|ADR|ADS|"
    r"NEW|DEL|THE|TR|TRUST|ETF|FUND|SPONSORED|SPON|US|[ABC])\b")
_ABBREV = {"MFG": "MANUFACTURING", "INTL": "INTERNATIONAL", "SVCS": "SERVICES",
           "FINL": "FINANCIAL", "TECHNOLOGIES": "TECHNOLOGY", "PLATFORMS": "PLATFORM",
           "LABS": "LABORATORIES", "COMMUNICATIONS": "COMMUNICATION"}


def _fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _norm_name(name):
    s = re.sub(r"\s+-\s+[A-Z]{2}$", "", name.upper().strip())  # Tudor "- US" tag
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = _SUFFIX.sub(" ", s)
    words = [_ABBREV.get(w, w) for w in s.split()]
    return " ".join(words)


def _ticker_lookup():
    """{normalized issuer name: ticker} from the SEC map (7d cache via edgar)."""
    cached = cache_get("quotes", ["symbol"], ["__SM_NAMEMAP__"], HOLDINGS_TTL)
    if cached:
        return json.loads(cached)
    raw = json.loads(_fetch(TICKER_MAP_URL))
    out = {}
    for v in raw.values():
        key = _norm_name(v["title"])
        if key and key not in out:  # first (largest) wins on collisions
            out[key] = v["ticker"].upper()
    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              ["__SM_NAMEMAP__", json.dumps(out), time.time()])
    return out


def _last_two_13f(cik):
    """[(period, accession), ...] latest two 13F-HR reports."""
    sub = json.loads(_fetch(SUBMISSIONS_URL.format(cik=cik)))
    recent = sub.get("filings", {}).get("recent", {})
    seen = {}
    for form, acc, period in zip(recent.get("form", []),
                                 recent.get("accessionNumber", []),
                                 recent.get("reportDate", [])):
        if form == "13F-HR" and period and period not in seen:
            seen[period] = acc
    periods = sorted(seen.keys(), reverse=True)[:2]
    return [(p, seen[p]) for p in periods]


def _info_table(cik, accession):
    """Aggregated holdings {(name, putCall): {value, shares}} from one 13F."""
    acc = accession.replace("-", "")
    idx = json.loads(_fetch(INDEX_URL.format(cik=cik, acc=acc)))
    xml_files = [f["name"] for f in idx.get("directory", {}).get("item", [])
                 if f["name"].lower().endswith(".xml")
                 and "primary_doc" not in f["name"].lower()]
    if not xml_files:
        return {}
    raw = _fetch(ARCHIVE_URL.format(cik=cik, acc=acc, file=xml_files[0]))
    root = ET.fromstring(raw)
    holdings = {}
    for it in root.iter():
        if not it.tag.endswith("infoTable"):
            continue
        name = (it.findtext("{*}nameOfIssuer") or "").strip()
        cusip = (it.findtext("{*}cusip") or "").strip().upper()
        put_call = (it.findtext("{*}putCall") or "").strip() or None
        value = float(it.findtext("{*}value") or 0)
        shares = float(it.findtext("{*}shrsOrPrnAmt/{*}sshPrnamt") or 0)
        key = f"{cusip}||{put_call or ''}"
        h = holdings.setdefault(key, {"name": name, "cusip": cusip,
                                      "putCall": put_call,
                                      "value": 0.0, "shares": 0.0})
        h["value"] += value
        h["shares"] += shares
    return holdings


FIGI_URL = "https://api.openfigi.com/v3/mapping"


def _resolve_cusips(entries):
    """{cusip: ticker or None}. Name match first, OpenFIGI for the rest
    (free, no key, 25 req/min × 10 jobs). Resolutions cached ~forever —
    a CUSIP never changes its meaning."""
    names = _ticker_lookup()
    out, pending = {}, []
    for cusip, name in entries:
        cached = cache_get("quotes", ["symbol"], [f"__CUSIP_{cusip}__"],
                           365 * 24 * 3600)
        if cached is not None:
            out[cusip] = json.loads(cached)
            continue
        tk = names.get(_norm_name(name))
        if tk:
            out[cusip] = tk
            cache_put("quotes", ["symbol", "payload", "fetched_at"],
                      [f"__CUSIP_{cusip}__", json.dumps(tk), time.time()])
        else:
            pending.append(cusip)
    for i in range(0, len(pending), 10):
        batch = pending[i:i + 10]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c}
                           for c in batch]).encode()
        req = urllib.request.Request(
            FIGI_URL, data=body,
            headers={**UA, "Content-Type": "application/json"})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            break  # rate-limited or down: leave rest unresolved this pass
        for cusip, job in zip(batch, res):
            data = job.get("data") or []
            tk = data[0].get("ticker") if data else None
            out[cusip] = tk
            cache_put("quotes", ["symbol", "payload", "fetched_at"],
                      [f"__CUSIP_{cusip}__", json.dumps(tk), time.time()])
        if i + 10 < len(pending):
            time.sleep(2.6)  # stay under 25 req/min keyless limit
    return out


def _manager_snapshot(cik):
    """Latest-vs-prior 13F comparison for one manager, cached 7d.
    Returns {period, prevPeriod, total, moves: {ticker: {...}}}."""
    key = f"__SM_{cik}__"
    cached = cache_get("quotes", ["symbol"], [key], HOLDINGS_TTL)
    if cached:
        return json.loads(cached)

    filings = _last_two_13f(cik)
    result = None
    if len(filings) == 2:
        (p_new, a_new), (p_old, a_old) = filings
        cur, prev = _info_table(cik, a_new), _info_table(cik, a_old)
        total = sum(h["value"] for h in cur.values()) or 1.0
        # resolve meaningful positions only: >=0.02% of book or top-500 by value
        combined = {}
        for tbl in (cur, prev):
            for h in tbl.values():
                combined.setdefault(h["cusip"], (h["name"], h["value"]))
        ranked = sorted(combined.items(), key=lambda kv: kv[1][1], reverse=True)
        tickers = _resolve_cusips([(c, nm) for c, (nm, _v) in ranked[:500]])
        moves = {}
        for k in set(cur) | set(prev):
            c, o = cur.get(k), prev.get(k)
            put_call = (c or o)["putCall"]
            ticker = tickers.get((c or o)["cusip"])
            if not ticker:
                continue
            cs, os_ = (c or {}).get("shares", 0.0), (o or {}).get("shares", 0.0)
            if c and not o:
                action = "new"
            elif o and not c:
                action = "exit"
            elif cs > os_ * 1.03:
                action = "add"
            elif cs < os_ * 0.97:
                action = "reduce"
            else:
                action = "hold"
            weight = round(((c or {}).get("value", 0.0)) / total * 100, 2)
            entry = moves.setdefault(ticker, [])
            entry.append({"action": action, "putCall": put_call,
                          "pctPortfolio": weight, "issuer": (c or o)["name"]})
        result = {"period": p_new, "prevPeriod": p_old, "moves": moves}
    payload = json.dumps(result)
    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              [key, payload, time.time()])
    return result


# score contribution per action, scaled by position significance
_ACTION_BASE = {"new": 10, "add": 7, "hold": 2, "reduce": -7, "exit": -10}


def score_moneyflow(symbol: str) -> dict:
    """Money Flow layer score for one ticker. None if no tracked manager
    touched the name in either of the last two quarters."""
    symbol = symbol.upper().split(".")[0]  # 13F covers US listings only
    detail, parts = [], []
    latest_period = None
    for cik, meta in MANAGERS.items():
        try:
            snap = _manager_snapshot(cik)
        except Exception:
            continue
        if not snap:
            continue
        latest_period = latest_period or snap["period"]
        for mv in snap["moves"].get(symbol, []):
            base = _ACTION_BASE[mv["action"]]
            # options express direction, not size: puts bearish, calls mildly bullish
            if mv["putCall"] == "Put":
                base = -6 if mv["action"] in ("new", "add", "hold") else 3
            elif mv["putCall"] == "Call":
                base = min(base, 4) if base > 0 else base
            # significance: a 5%+ position moves the needle fully, dust barely
            sig = min(1.0, 0.3 + mv["pctPortfolio"] / 5.0 * 0.7)
            parts.append(base * sig)
            label = {"new": "NEW BUY", "add": "ADD", "hold": "HOLD",
                     "reduce": "REDUCE", "exit": "FULL EXIT"}[mv["action"]]
            opt = f" ({mv['putCall']})" if mv["putCall"] else ""
            detail.append(f"{meta['name']}: {label}{opt} — "
                          f"{mv['pctPortfolio']}% of their portfolio")

    if not parts:
        return {"score": None, "notes": ["No tracked super-investor holds or "
                                         "traded this name (not a bearish signal "
                                         "— 13Fs only show US-listed longs)"],
                "managersTracked": len(MANAGERS)}
    score = max(0, min(100, round(50 + sum(parts) * 2)))
    return {"score": score, "notes": detail,
            "asOf": latest_period,
            "caveats": ["13F data lags ~45 days; shorts and non-US lines invisible",
                        "Copying trades ≠ copying conviction — managers hedge elsewhere"],
            "managersTracked": len(MANAGERS)}


def flows_overview() -> dict:
    """Dashboard panel: each manager's biggest moves last quarter."""
    out = []
    for cik, meta in MANAGERS.items():
        try:
            snap = _manager_snapshot(cik)
        except Exception:
            snap = None
        if not snap:
            continue
        flat = []
        for tk, mvs in snap["moves"].items():
            for mv in mvs:
                if mv["action"] in ("new", "add", "reduce", "exit"):
                    flat.append({"ticker": tk, **mv})
        flat.sort(key=lambda m: m["pctPortfolio"], reverse=True)
        out.append({"manager": meta["name"], "style": meta["style"],
                    "period": snap["period"], "topMoves": flat[:8]})
    return {"managers": out,
            "source": "SEC EDGAR 13F-HR (official, free, ~45d lag)"}
