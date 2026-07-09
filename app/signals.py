"""Five-layer signal engine — hybrid gate + score (locked design).

Layers and locked weights:
  SECULAR  -> gate (not scored): CAPE > 38 = caution regime, blocks fresh BUY
  SELECTION 35% -> strategy.score_selection (Graham/Lynch/value)
  TACTICAL  20% -> trend/relative position of price in its own regime
  TIMING    20% -> RSI, MACD, MA cross, Fibonacci pullback zone (confluence)
  RISK      25% -> margin of safety (Graham number), volatility, leverage

Composite 0-100. BUY requires: score >= 70 AND all hard gates pass.
Every layer returns its inputs for the transparency drill-down.
"""
import json
import re
import time
import urllib.request

import fetcher
import strategy
from db import cache_get, cache_put

CAPE_TTL = 24 * 3600
CAPE_GATE = 38.0  # research-backed: 10yr forward real returns poor above this
MULTPL_URL = "https://www.multpl.com/shiller-pe"

WEIGHTS = {"selection": 0.35, "tactical": 0.20, "timing": 0.20, "risk": 0.25}


# ---------------- SECULAR ----------------

def get_cape() -> dict:
    cached = cache_get("quotes", ["symbol"], ["__CAPE__"], CAPE_TTL)
    if cached:
        return json.loads(cached)
    req = urllib.request.Request(MULTPL_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    m = re.search(r"Current Shiller PE Ratio[^0-9]*([0-9]+\.[0-9]+)", html)
    value = float(m.group(1)) if m else None
    payload = {"cape": value, "gate": CAPE_GATE,
               "caution": value is not None and value > CAPE_GATE,
               "source": "multpl.com (Shiller data)", "fetchedAt": time.time()}
    cache_put("quotes", ["symbol", "payload", "fetched_at"],
              ["__CAPE__", json.dumps(payload), time.time()])
    return payload


# ---------------- indicator math (pure python, no deps) ----------------

def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def macd_signal(closes):
    """Returns (macd_line, signal_line, histogram) on latest bar, or None."""
    if len(closes) < 35:
        return None
    macd_series = []
    for i in range(26, len(closes) + 1):
        window = closes[:i]
        e12, e26 = ema(window, 12), ema(window, 26)
        if e12 is None or e26 is None:
            continue
        macd_series.append(e12 - e26)
    if len(macd_series) < 9:
        return None
    sig = ema(macd_series, 9)
    line = macd_series[-1]
    return round(line, 4), round(sig, 4), round(line - sig, 4)


def realized_vol(closes, window=60):
    """Annualized stdev of daily returns over the window, %."""
    if len(closes) < window + 1:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round((var ** 0.5) * (252 ** 0.5) * 100, 1)


# ---------------- layer scores ----------------

def score_tactical(q, closes):
    """Trend regime: price vs MAs, relative position in 52w range."""
    parts, notes = [], []
    price = q.get("price")
    ma50, ma200 = q.get("fiftyDayAverage"), q.get("twoHundredDayAverage")
    hi, lo = q.get("fiftyTwoWeekHigh"), q.get("fiftyTwoWeekLow")

    if price and ma200:
        up = price > ma200
        parts.append(60 if up else 30)
        notes.append(f"Price {'above' if up else 'below'} 200d MA — long-term trend {'intact' if up else 'broken'}")
    if ma50 and ma200:
        golden = ma50 > ma200
        parts.append(70 if golden else 35)
        notes.append(f"50d {'above' if golden else 'below'} 200d MA ({'golden' if golden else 'death'}-cross regime)")
    if price and hi and lo and hi > lo:
        pos = (price - lo) / (hi - lo)  # 0 = at 52w low, 1 = at high
        # sweet spot for accumulation: not collapsed, not at euphoric high
        s = 75 if 0.35 <= pos <= 0.75 else (50 if pos < 0.35 else 40)
        parts.append(s)
        notes.append(f"Position in 52w range: {round(pos * 100)}% (0=low, 100=high)")

    if not parts:
        return {"score": None, "notes": ["insufficient data"]}
    return {"score": round(sum(parts) / len(parts)), "notes": notes}


def score_timing(q, closes):
    """Confluence: RSI + MACD + Fibonacci pullback zone. Never one signal alone."""
    parts, notes = [], []
    price = q.get("price")
    hi, lo = q.get("fiftyTwoWeekHigh"), q.get("fiftyTwoWeekLow")

    r = rsi(closes)
    if r is not None:
        if r < 30:
            parts.append(80); notes.append(f"RSI {r} — oversold (potential accumulation, confirm with trend)")
        elif r > 70:
            parts.append(25); notes.append(f"RSI {r} — overbought (chasing strength)")
        else:
            parts.append(55); notes.append(f"RSI {r} — neutral zone")

    m = macd_signal(closes)
    if m:
        line, sig, hist = m
        bullish = hist > 0
        parts.append(65 if bullish else 40)
        notes.append(f"MACD histogram {hist} — {'bullish' if bullish else 'bearish'} momentum")

    # Fibonacci retracement of the 52w swing (low -> high), pullback entry zones
    if price and hi and lo and hi > lo:
        fib382 = hi - 0.382 * (hi - lo)
        fib50 = hi - 0.500 * (hi - lo)
        fib618 = hi - 0.618 * (hi - lo)
        if fib618 <= price <= fib382:
            parts.append(75)
            notes.append(f"Price in Fibonacci pullback zone (38.2–61.8% of 52w swing: "
                         f"{round(fib618, 2)}–{round(fib382, 2)}) — classic accumulation band")
        elif price > fib382:
            parts.append(45)
            notes.append("Above the 38.2% retracement — extended, no pullback discount")
        else:
            parts.append(35)
            notes.append("Below the 61.8% retracement — deep breakdown, wave structure in question")

    if not parts:
        return {"score": None, "notes": ["insufficient history"]}
    return {"score": round(sum(parts) / len(parts)), "notes": notes}


def score_risk(q, closes):
    """Margin of safety (Graham number), leverage, volatility regime.
    Hard gate: negative margin of safety > 50% overpriced = block."""
    parts, notes = [], []
    gates_failed = []

    eps = q.get("trailingEps") if q.get("trailingEps") else None
    bvps = q.get("bookValue") if q.get("bookValue") else None
    price = q.get("price")

    mos = None
    if eps and bvps and price and eps > 0 and bvps > 0:
        graham_number = (22.5 * eps * bvps) ** 0.5
        mos = (graham_number - price) / graham_number  # >0 = trading below fair value
        if mos >= 0.20:
            parts.append(90); notes.append(f"Margin of safety {round(mos*100)}% vs Graham number {round(graham_number,2)} — strong buffer")
        elif mos > 0:
            parts.append(65); notes.append(f"Margin of safety {round(mos*100)}% — thin buffer, below the 20% bar")
        else:
            parts.append(25); notes.append(f"NEGATIVE margin of safety ({round(mos*100)}%) — price above Graham fair value")
            if mos < -0.50:
                gates_failed.append("Price more than 50% above Graham number — hard risk gate")

    de = q.get("debtToEquity")
    if de is not None:
        ok = de <= 150
        parts.append(70 if de <= 100 else (50 if ok else 25))
        notes.append(f"Debt/Equity {round(de)}% — {'conservative' if de <= 100 else 'elevated' if ok else 'high leverage'}")

    vol = realized_vol(closes)
    if vol is not None:
        s = 70 if vol < 25 else (50 if vol < 40 else 30)
        parts.append(s)
        notes.append(f"Realized volatility {vol}% annualized — position size should scale inversely (rule #17)")

    if not parts:
        return {"score": None, "notes": ["insufficient data"], "gatesFailed": []}
    return {"score": round(sum(parts) / len(parts)), "notes": notes,
            "gatesFailed": gates_failed, "marginOfSafety": mos}


# ---------------- composite ----------------

def full_signal(symbol: str) -> dict:
    q = fetcher.get_quote(symbol)
    # need eps/bookValue for Graham number — add on demand if missing
    history = fetcher.get_history(symbol, "1y")
    closes = [row["close"] for row in history]

    secular = get_cape()
    selection = strategy.score_selection(q)
    tactical = score_tactical(q, closes)
    timing = score_timing(q, closes)
    risk = score_risk(q, closes)

    layers = {
        "selection": selection.get("score"),
        "tactical": tactical.get("score"),
        "timing": timing.get("score"),
        "risk": risk.get("score"),
    }

    # composite over layers that produced a score, reweighted
    avail = {k: v for k, v in layers.items() if v is not None}
    if avail:
        total_w = sum(WEIGHTS[k] for k in avail)
        composite = round(sum(v * WEIGHTS[k] for k, v in avail.items()) / total_w)
    else:
        composite = None

    hard_gates = list(risk.get("gatesFailed", []))
    secular_caution = secular.get("caution", False)

    if composite is None:
        verdict = "NO DATA"
    elif hard_gates:
        verdict = "BLOCKED"
    elif composite >= 70 and not secular_caution:
        verdict = "BUY"
    elif composite >= 70 and secular_caution:
        verdict = "WATCH"  # score clears but secular regime blocks fresh buys
    elif composite >= 50:
        verdict = "WATCH"
    else:
        verdict = "AVOID"

    return {
        "symbol": q["symbol"],
        "name": q.get("name"),
        "sector": q.get("sector"),
        "price": q.get("price"),
        "currency": q.get("currency"),
        "composite": composite,
        "verdict": verdict,
        "weights": WEIGHTS,
        "secular": secular,
        "secularCaution": secular_caution,
        "hardGates": hard_gates,
        "layers": {
            "selection": selection,
            "tactical": tactical,
            "timing": timing,
            "risk": {k: v for k, v in risk.items() if k != "gatesFailed"},
        },
        "methodology": {
            "compositeFormula": "Selection 35% + Tactical 20% + Timing 20% + Risk 25%, gated by Secular (CAPE) and hard risk gates",
            "buyThreshold": 70,
            "historyBars": len(closes),
            "dataSource": "Yahoo Finance (yfinance), ECB, multpl.com Shiller data",
            "caveats": [
                "Phase 2 heuristics — thresholds NOT yet backtest-calibrated (Model Health will track this)",
                "Fibonacci zone uses 52-week swing, not wave-count analysis",
                "Secular gate is market-wide (US CAPE), applied to all tickers",
            ],
        },
    }
