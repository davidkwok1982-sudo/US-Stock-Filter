"""SQLite cache for screen snapshots, daily bars, and fundamentals."""

from __future__ import annotations

import json
from pathlib import Path
import logging
import threading
import sqlite3
import zlib
from datetime import datetime, timezone

from app.config import CACHE_DIR, DB_PATH, TTL_HOURS
from app.markets import HK_MARKET, US_MARKET, get_market

log = logging.getLogger("kailut")

_mem_lock = threading.Lock()
_mem_snapshots: dict[str, dict | None] = {"us": None, "hk": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charts (
    symbol TEXT PRIMARY KEY,
    payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _db_path(market: str = "us") -> Path:
    if market == "hk":
        return CACHE_DIR / HK_MARKET.db_name
    if market == "us":
        # Keep historical default path for the US cache.
        return DB_PATH if US_MARKET.db_name == "market.sqlite" else CACHE_DIR / US_MARKET.db_name
    cfg = get_market(market)
    return CACHE_DIR / cfg.db_name


def _connect(market: str = "us") -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(market), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(market: str = "us") -> None:
    with _connect(market) as conn:
        conn.executescript(SCHEMA)


def _pack(bars: list[dict]) -> bytes:
    payload = {
        "t": [bar["time"] for bar in bars],
        "o": [round(bar["open"], 4) for bar in bars],
        "h": [round(bar["high"], 4) for bar in bars],
        "l": [round(bar["low"], 4) for bar in bars],
        "c": [round(bar["close"], 4) for bar in bars],
        "v": [int(bar["volume"]) for bar in bars],
        "d": [round(bar["dollar"], 2) for bar in bars],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return zlib.compress(raw, level=6)


def _unpack(blob: bytes) -> list[dict]:
    payload = json.loads(zlib.decompress(blob))
    bars = []
    for index, day in enumerate(payload["t"]):
        bars.append(
            {
                "time": day,
                "open": payload["o"][index],
                "high": payload["h"][index],
                "low": payload["l"][index],
                "close": payload["c"][index],
                "volume": payload["v"][index],
                "dollar": payload["d"][index],
            }
        )
    return bars



def _refresh_screen_cache(snapshot: dict, market: str = "us") -> None:
    """Rebuild in-memory pre-serialized /api/screen payloads after snapshot writes."""
    try:
        from app import screen_cache
        from app.engine import engines

        eng = engines[market]
        screen_cache.rebuild(snapshot, eng.status(), is_stale(snapshot), market=market)
    except Exception as exc:  # pragma: no cover - cache must never break persistence
        log.warning("screen cache rebuild failed (%s): %s", market, exc)
        try:
            from app import screen_cache

            screen_cache.invalidate(market=market)
        except Exception:
            pass


def save_refresh(snapshot: dict, charts: dict[str, list[dict]], market: str = "us") -> None:
    init_db(market)
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    rows = [(symbol, _pack(bars)) for symbol, bars in charts.items()]
    with _connect(market) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM charts")
        conn.executemany("INSERT INTO charts (symbol, payload) VALUES (?, ?)", rows)
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('snapshot', ?)", (encoded,))
        conn.commit()
    with _mem_lock:
        _mem_snapshots[market] = snapshot
    _refresh_screen_cache(snapshot, market)


def save_snapshot(snapshot: dict, market: str = "us") -> None:
    """Overwrite the screen snapshot without touching cached charts."""
    init_db(market)
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    with _connect(market) as conn:
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('snapshot', ?)", (encoded,))
        conn.commit()
    with _mem_lock:
        _mem_snapshots[market] = snapshot
    _refresh_screen_cache(snapshot, market)


def load_snapshot(market: str = "us") -> dict | None:
    with _mem_lock:
        cached = _mem_snapshots.get(market)
        if cached is not None:
            return cached
    init_db(market)
    with _connect(market) as conn:
        row = conn.execute("SELECT v FROM kv WHERE k = 'snapshot'").fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["v"])
    with _mem_lock:
        _mem_snapshots[market] = snapshot
    return snapshot


def load_chart(symbol: str, market: str = "us") -> list[dict] | None:
    found = load_charts([symbol], market=market)
    return found.get(symbol)


def load_charts(symbols: list[str], market: str = "us") -> dict[str, list[dict]]:
    """Load daily bars for the given symbols. Missing symbols are omitted."""
    if not symbols:
        return {}
    init_db(market)
    found: dict[str, list[dict]] = {}
    # Stay under SQLite's default bound-variable limit.
    chunk_size = 400
    with _connect(market) as conn:
        for start in range(0, len(symbols), chunk_size):
            chunk = symbols[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT symbol, payload FROM charts WHERE symbol IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                found[row["symbol"]] = _unpack(row["payload"])
    return found


def save_chart(symbol: str, bars: list[dict], market: str = "us") -> None:
    init_db(market)
    with _connect(market) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charts (symbol, payload) VALUES (?, ?)",
            (symbol, _pack(bars)),
        )


def upsert_charts(charts: dict[str, list[dict]], market: str = "us") -> None:
    """Insert or replace chart rows without wiping the rest of the cache."""
    if not charts:
        return
    init_db(market)
    rows = [(symbol, _pack(bars)) for symbol, bars in charts.items()]
    with _connect(market) as conn:
        conn.execute("BEGIN")
        conn.executemany("INSERT OR REPLACE INTO charts (symbol, payload) VALUES (?, ?)", rows)
        conn.commit()


def prune_charts(keep: set[str], market: str = "us") -> None:
    """Drop cached charts whose symbols are no longer in the universe (+ benchmark)."""
    init_db(market)
    with _connect(market) as conn:
        existing = [row[0] for row in conn.execute("SELECT symbol FROM charts").fetchall()]
        drop = [symbol for symbol in existing if symbol not in keep]
        if not drop:
            return
        conn.execute("BEGIN")
        conn.executemany("DELETE FROM charts WHERE symbol = ?", [(symbol,) for symbol in drop])
        conn.commit()


def load_fundamentals(symbol: str, market: str = "us") -> dict | None:
    init_db(market)
    with _connect(market) as conn:
        row = conn.execute(
            "SELECT payload, updated_at FROM fundamentals WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload["updatedAt"] = row["updated_at"]
    return payload


def save_fundamentals(symbol: str, payload: dict, market: str = "us") -> None:
    init_db(market)
    stamp = datetime.now(timezone.utc).isoformat()
    with _connect(market) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (symbol, payload, updated_at) VALUES (?, ?, ?)",
            (symbol, json.dumps(payload, ensure_ascii=False), stamp),
        )


def age_seconds(snapshot: dict) -> float | None:
    raw = (snapshot.get("meta") or {}).get("refreshedAt")
    if not raw:
        return None
    stamp = datetime.fromisoformat(raw)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def is_stale(snapshot: dict, ttl_hours: float = TTL_HOURS) -> bool:
    age = age_seconds(snapshot)
    if age is None:
        return True
    return age > ttl_hours * 3600
