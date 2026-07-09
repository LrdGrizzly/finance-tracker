# Finance Tracker

Local, free-forever investment dashboard. Phase 1.

## Run it

Open PowerShell and paste:

```powershell
cd "<path-to-project>\finance tracker"
python -m venv venv            # first time only
.\venv\Scripts\python -m pip install flask yfinance   # first time only
.\venv\Scripts\python app\server.py
```

Expected output:

```
Finance Tracker running at http://localhost:5001
```

Then open **http://localhost:5001** in your browser. Leave the PowerShell window open while using the app; close it (or press Ctrl+C) to stop.

## Folder map

```
app/        Python backend (Flask server, yfinance fetcher, SQLite cache)
web/        Frontend (HTML/CSS/JS, PWA manifest)
data/       YOUR data — watchlist.json, holdings.json  → sync this via Google Drive
cache/      Market data cache (SQLite) — local only, NEVER sync, safe to delete
venv/       Python environment — local only, never sync
```

## What works now (Phase 1)

- **Home** — snapshot counts
- **Ticker Monitor** — any ticker: live quote, value-investing fundamentals grid
  (P/E, P/B, PEG, ROE, debt/equity, current ratio, dividend yield, 50/200d MA,
  52w range), sector pill, expandable TradingView interactive chart
- **Watchlist** — add/remove tickers, live prices, sector pills, click row → full analysis
- **Portfolio** — log purchases (date/price/qty), live P/L per position,
  total in EUR
- **Maintenance** — data source health checks (Yahoo, ECB FX)
- **EUR hover** — hover any non-EUR amount → EUR conversion (ECB daily rate)
- Quotes auto-refresh every 5 minutes while the app is open

## Phase 2 (planned, spec locked in memory)

Screening pipeline (Magic Formula + Graham + Lynch over S&P 500 + STOXX 600),
signal engine (hybrid gate + score), Suggestions tab, Heatmaps/Market Pulse,
Learn/Academy curriculum, Model Health + calculation transparency, backtesting.
