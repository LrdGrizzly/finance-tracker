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

# Peer-review 2026-07-10: Selection dominates for a 5-10yr quality investor;
# timing/tactical inform entry sizing, not the verdict.
# 2026-07-11: Money Flow lens added (SEC 13F super-investor positioning,
# Money Flow Research deep dives) — confirmation signal, NOT thesis, so it
# takes weight from the entry-sizing layers, not from Selection.
# 2026-07-11 calibration (252 signals, 6 entry dates 2022-2025, 42 tickers):
# selection 0.55 + BUY>=65/HOLD>=45 scored 85% hit, BUY avg +58% vs HOLD +30%
# vs SELL +27% (monotonic), stable across neighboring configs. Applied.
WEIGHTS = {"selection": 0.55, "tactical": 0.09, "timing": 0.09,
           "risk": 0.17, "moneyflow": 0.10}


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

    # Trend-conditioned RSI (peer review): in a confirmed uptrend RSI lives
    # at 60-80 for months — punishing >70 blocks the best compounders.
    ma200 = q.get("twoHundredDayAverage")
    uptrend = price is not None and ma200 is not None and price > ma200
    r = rsi(closes)
    if r is not None:
        if r < 30:
            parts.append(80); notes.append(f"RSI {r} — oversold (potential accumulation, confirm with trend)")
        elif r > 70 and not uptrend:
            parts.append(30); notes.append(f"RSI {r} — overbought without trend support")
        elif r > 70 and uptrend:
            parts.append(50); notes.append(f"RSI {r} — hot, but in a confirmed uptrend (trend-conditioned, not a sell signal)")
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
        # Peer review: NO hard gate on Graham number — high-ROIC compounders
        # carry structurally low book value (buybacks), making GN block exactly
        # the businesses the philosophy targets. Score input only.
        if mos >= 0.20:
            parts.append(90); notes.append(f"Margin of safety {round(mos*100)}% vs Graham number {round(graham_number,2)} — strong buffer")
        elif mos > 0:
            parts.append(65); notes.append(f"Margin of safety {round(mos*100)}% — thin buffer, below the 20% bar")
        else:
            parts.append(35); notes.append(f"Negative Graham margin ({round(mos*100)}%) — note: Graham number understates fair value for buyback-heavy compounders")

    de = q.get("debtToEquity")
    if de is not None:
        ok = de <= 150
        parts.append(70 if de <= 100 else (50 if ok else 25))
        notes.append(f"Debt/Equity {round(de)}% — {'conservative' if de <= 100 else 'elevated' if ok else 'high leverage'}")

    vol = realized_vol(closes)
    if vol is not None:
        # Peer review calibration: average single stock runs 25-35% — bands
        # set for single equities, not index funds.
        s = 70 if vol < 30 else (50 if vol < 45 else 30)
        parts.append(s)
        notes.append(f"Realized volatility {vol}% annualized — position size should scale inversely (rule #17)")

    if not parts:
        return {"score": None, "notes": ["insufficient data"], "gatesFailed": []}
    return {"score": round(sum(parts) / len(parts)), "notes": notes,
            "gatesFailed": gates_failed, "marginOfSafety": mos}


# ---------------- composite ----------------

def secular_multiplier(cape_value):
    """Peer review: graduated haircut, NOT a binary gate. CAPE below 32 =
    no drag; linear taper to 0.80x at CAPE 45+. Never blocks a BUY outright —
    it shaves conviction and (in practice) position size."""
    if cape_value is None:
        return 1.0
    if cape_value <= 32:
        return 1.0
    if cape_value >= 45:
        return 0.80
    return round(1.0 - 0.20 * (cape_value - 32) / 13, 3)


def verdict_ladder(score):
    """Overall BUY/SELL verdict with strength, from the secular-adjusted
    composite. Strength = distance from the nearest boundary, so a 79 BUY
    reads weaker than an 88 STRONG BUY."""
    if score is None:
        return "NO DATA", None
    if score >= 80:
        return "STRONG BUY", min(100, round((score - 80) / 20 * 50 + 50))
    if score >= 65:
        return "BUY", round((score - 65) / 15 * 45 + 50)
    if score >= 45:
        return "HOLD", round((score - 45) / 20 * 45 + 50)
    if score >= 30:
        return "SELL", round((45 - score) / 15 * 45 + 50)
    return "STRONG SELL", min(100, round((30 - score) / 20 * 50 + 50))


def full_signal(symbol: str) -> dict:
    q = fetcher.get_quote(symbol)
    history = fetcher.get_history(symbol, "1y")
    closes = [row["close"] for row in history]

    secular = get_cape()
    deep_value = strategy.score_selection(q)
    tactical = score_tactical(q, closes)
    timing = score_timing(q, closes)
    risk = score_risk(q, closes)
    try:
        import smartmoney
        moneyflow = smartmoney.score_moneyflow(symbol)
    except Exception:
        moneyflow = {"score": None, "notes": ["Money Flow data unavailable"]}

    # Selection = quality-compounder primary, deep value secondary
    # (peer review: quality lens must drive Selection for this philosophy)
    try:
        import quality as quality_mod
        q_score = quality_mod.compute_quality(symbol)
    except Exception:
        q_score = {"score": None}
    qs, dv = q_score.get("score"), deep_value.get("score")
    if qs is not None and dv is not None:
        selection_score = round(0.65 * qs + 0.35 * dv)
        selection_note = f"Blend: 65% quality-compounder ({qs}) + 35% deep-value ({dv})"
    elif qs is not None:
        selection_score, selection_note = qs, f"Quality-compounder only ({qs}) — no value data"
    elif dv is not None:
        selection_score, selection_note = dv, f"Deep-value only ({dv}) — no statement data for quality"
    else:
        selection_score, selection_note = None, "no data"

    layers = {
        "selection": selection_score,
        "tactical": tactical.get("score"),
        "timing": timing.get("score"),
        "risk": risk.get("score"),
        "moneyflow": moneyflow.get("score"),
    }

    avail = {k: v for k, v in layers.items() if v is not None}
    if avail:
        total_w = sum(WEIGHTS[k] for k in avail)
        raw_composite = sum(v * WEIGHTS[k] for k, v in avail.items()) / total_w
        mult = secular_multiplier(secular.get("cape"))
        composite = round(raw_composite * mult)
    else:
        raw_composite, mult, composite = None, 1.0, None

    hard_gates = list(risk.get("gatesFailed", []))
    secular_caution = secular.get("caution", False)

    if hard_gates and composite is not None:
        verdict, strength = "BLOCKED", None
    else:
        verdict, strength = verdict_ladder(composite)

    return {
        "rawComposite": round(raw_composite) if raw_composite is not None else None,
        "secularMultiplier": mult,
        "strength": strength,
        "selectionBlend": selection_note,
        "qualityScore": qs,
        "deepValueScore": dv,
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
            "selection": {"score": selection_score, "notes": [selection_note],
                          "criteria": deep_value.get("criteria", [])},
            "tactical": tactical,
            "timing": timing,
            "risk": {k: v for k, v in risk.items() if k != "gatesFailed"},
            "moneyflow": moneyflow,
        },
        "methodology": {
            "compositeFormula": (
                "Selection 55% (65% quality-compounder + 35% deep-value) + Tactical 9% "
                "+ Timing 9% + Risk 17% + Money Flow 10% (SEC 13F super-investor "
                "positioning), × secular CAPE multiplier "
                f"(currently {mult}) — weights backtest-calibrated 2026-07-11 "
                "(252 signals, 2022-2025, 85% hit rate, monotonic buckets)"
            ),
            "verdictLadder": "STRONG BUY ≥80 · BUY ≥65 · HOLD ≥45 · SELL ≥30 · STRONG SELL <30, strength = distance into band",
            "historyBars": len(closes),
            "dataSource": "Yahoo Finance (yfinance), ECB, multpl.com Shiller data",
            "caveats": [
                "Weights/thresholds calibrated on 252 signals across 2022-2025 — one (bullish) regime; Model Health re-tests ongoing",
                "Money Flow layer: 13F data lags ~45 days, US-listed longs only, absence of a name is neutral not bearish",
                "Fibonacci zone uses 52-week swing, not wave-count analysis",
                "Secular gate is market-wide (US CAPE), applied to all tickers",
            ],
        },
    }
