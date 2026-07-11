"""Flusso-style local server for the finance tracker.

Run:  venv\\Scripts\\python app\\server.py
Then open http://localhost:5001 in your browser.

Editable data (watchlist, holdings) lives in ../data/*.json — Drive-syncable.
Market data cache lives in ../cache/market_cache.db — local only.
"""
import json
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import backtest
import fetcher
import quality
import screener
import signals
import smartmoney
import strategy

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

WATCHLIST_FILE = DATA_DIR / "watchlist.json"
HOLDINGS_FILE = DATA_DIR / "holdings.json"

app = Flask(__name__, static_folder=None)


# ---------- JSON file stores (Drive-synced, last-write-wins timestamps) ----

def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, data):
    data["updatedAt"] = time.time()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------- static frontend ----------

@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB_DIR, filename)


# ---------- market data API ----------

@app.get("/api/quote/<symbol>")
def api_quote(symbol):
    try:
        return jsonify(fetcher.get_quote(symbol))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/history/<symbol>")
def api_history(symbol):
    period = request.args.get("period", "1y")
    interval = request.args.get("interval", "1d")
    try:
        return jsonify(fetcher.get_history(symbol, period, interval))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/fit/<symbol>")
def api_fit(symbol):
    try:
        q = fetcher.get_quote(symbol)
        return jsonify(strategy.score_selection(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/quality/<symbol>")
def api_quality(symbol):
    try:
        return jsonify(quality.compute_quality(symbol))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/signal/<symbol>")
def api_signal(symbol):
    try:
        return jsonify(signals.full_signal(symbol))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.post("/api/screen/start")
def api_screen_start():
    body = request.get_json(silent=True) or {}
    return jsonify(screener.start(limit=body.get("limit")))


@app.get("/api/screen/status")
def api_screen_status():
    return jsonify(screener.status())


@app.post("/api/screen/stop")
def api_screen_stop():
    return jsonify(screener.stop())


@app.get("/api/screen/results")
def api_screen_results():
    return jsonify(screener.results(
        min_graham=int(request.args.get("min_graham", 2)),
        top=int(request.args.get("top", 50)),
    ))


@app.post("/api/backtest/run")
def api_backtest_run():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(backtest.run_backtest(
            tickers=body.get("tickers"),
            entry_date=body.get("entryDate", "2025-06-30"),
        ))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/backtest/latest")
def api_backtest_latest():
    run = backtest.latest_run()
    return jsonify(run or {"empty": True})


@app.post("/api/backtest/calibrate")
def api_backtest_calibrate():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(backtest.run_calibration(
            tickers=body.get("tickers"),
            entry_dates=body.get("entryDates"),
        ))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/backtest/calibration")
def api_backtest_calibration():
    run = backtest.latest_calibration()
    return jsonify(run or {"empty": True})


@app.get("/api/moneyflow")
def api_moneyflow_overview():
    try:
        return jsonify(smartmoney.flows_overview())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/moneyflow/<symbol>")
def api_moneyflow_symbol(symbol):
    try:
        return jsonify(smartmoney.score_moneyflow(symbol))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        return jsonify(fetcher.search_symbols(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/fx")
def api_fx():
    try:
        return jsonify(fetcher.get_fx_rates())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ---------- watchlist ----------

@app.get("/api/watchlist")
def get_watchlist():
    return jsonify(_load(WATCHLIST_FILE, {"tickers": []}))


@app.post("/api/watchlist")
def add_to_watchlist():
    body = request.get_json(force=True)
    symbol = body.get("symbol", "").upper().strip()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    data = _load(WATCHLIST_FILE, {"tickers": []})
    if symbol not in [t["symbol"] for t in data["tickers"]]:
        data["tickers"].append({"symbol": symbol, "addedAt": time.time()})
        _save(WATCHLIST_FILE, data)
    return jsonify(data)


@app.delete("/api/watchlist/<symbol>")
def remove_from_watchlist(symbol):
    symbol = symbol.upper().strip()
    data = _load(WATCHLIST_FILE, {"tickers": []})
    data["tickers"] = [t for t in data["tickers"] if t["symbol"] != symbol]
    _save(WATCHLIST_FILE, data)
    return jsonify(data)


# ---------- holdings ----------

@app.get("/api/holdings")
def get_holdings():
    return jsonify(_load(HOLDINGS_FILE, {"positions": []}))


@app.post("/api/holdings")
def add_holding():
    body = request.get_json(force=True)
    required = ["symbol", "date", "price", "quantity"]
    missing = [k for k in required if not body.get(k)]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400
    data = _load(HOLDINGS_FILE, {"positions": []})
    data["positions"].append({
        "symbol": body["symbol"].upper().strip(),
        "date": body["date"],
        "price": float(body["price"]),
        "quantity": float(body["quantity"]),
        "note": body.get("note", ""),
        "addedAt": time.time(),
    })
    _save(HOLDINGS_FILE, data)
    return jsonify(data)


@app.delete("/api/holdings/<int:idx>")
def remove_holding(idx):
    data = _load(HOLDINGS_FILE, {"positions": []})
    if 0 <= idx < len(data["positions"]):
        data["positions"].pop(idx)
        _save(HOLDINGS_FILE, data)
    return jsonify(data)


if __name__ == "__main__":
    print("Finance Tracker running at http://localhost:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
