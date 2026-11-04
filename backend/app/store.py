"""SQLite cache for screen snapshots, daily bars, and fundamentals."""

from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import datetime, timezone

from app.config import CACHE_DIR, DB_PATH, TTL_HOURS

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


def _connect() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
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


def save_refresh(snapshot: dict, charts: dict[str, list[dict]]) -> None:
    init_db()
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    rows = [(symbol, _pack(bars)) for symbol, bars in charts.items()]
    with _connect() as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM charts")
        conn.executemany("INSERT INTO charts (symbol, payload) VALUES (?, ?)", rows)
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('snapshot', ?)", (encoded,))
        conn.commit()


def save_snapshot(snapshot: dict) -> None:
    """Overwrite the screen snapshot without touching cached charts."""
    init_db()
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('snapshot', ?)", (encoded,))
        conn.commit()


def load_snapshot() -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT v FROM kv WHERE k = 'snapshot'").fetchone()
    if row is None:
        return None
    return json.loads(row["v"])


def load_chart(symbol: str) -> list[dict] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM charts WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return None
    return _unpack(row["payload"])


def save_chart(symbol: str, bars: list[dict]) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO charts (symbol, payload) VALUES (?, ?)",
            (symbol, _pack(bars)),
        )


def load_fundamentals(symbol: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload, updated_at FROM fundamentals WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload["updatedAt"] = row["updated_at"]
    return payload


def save_fundamentals(symbol: str, payload: dict) -> None:
    init_db()
    stamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
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
