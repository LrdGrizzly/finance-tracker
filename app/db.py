"""SQLite cache layer — device-local, never synced, disposable.

Precious editable data (watchlist, holdings) lives in ../data/*.json
(Drive-syncable). This module only caches market data that can be
re-fetched at any time.
"""
import sqlite3
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
DB_PATH = CACHE_DIR / "market_cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    symbol      TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,      -- JSON blob from fetcher
    fetched_at  REAL NOT NULL       -- unix timestamp
);
CREATE TABLE IF NOT EXISTS history (
    symbol      TEXT NOT NULL,
    period      TEXT NOT NULL,      -- e.g. '1y', 'max'
    payload     TEXT NOT NULL,      -- JSON OHLCV rows
    fetched_at  REAL NOT NULL,
    PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    currency    TEXT PRIMARY KEY,   -- e.g. 'USD'
    rate_to_eur REAL NOT NULL,      -- 1 unit of currency = X EUR
    fetched_at  REAL NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def cache_get(table, key_cols, key_vals, max_age_seconds):
    """Return payload if cached and fresh, else None."""
    conn = get_conn()
    try:
        where = " AND ".join(f"{c} = ?" for c in key_cols)
        row = conn.execute(
            f"SELECT payload, fetched_at FROM {table} WHERE {where}", key_vals
        ).fetchone()
        if row and (time.time() - row["fetched_at"]) < max_age_seconds:
            return row["payload"]
        return None
    finally:
        conn.close()


def cache_put(table, cols, vals):
    conn = get_conn()
    try:
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.commit()
    finally:
        conn.close()
