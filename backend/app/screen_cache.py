"""In-memory serialized /api/screen responses (prefer pre-gzipped).

Rebuilt whenever the SQLite snapshot is saved. Default payload is passHard-only
rows (~hundreds) so heatmap/table stay fast; ?include=all keeps the full universe.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from typing import Any

from starlette.responses import Response

log = logging.getLogger("kailut")

# Fast enough for ~360KB passHard JSON; still used if we must re-gzip with live refresh.
_GZIP_LEVEL = 1
_SLIM_DROP = ("scoreParts", "beta", "betaBasis")

_lock = threading.Lock()
# market -> side -> include -> {"raw": bytes, "gzip": bytes, "refresh": dict, "stale": bool}
# Long and short payloads are separate so a warm long response cannot serve short rows.
_entries_by_market: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}


def _bucket(market: str = "us", side: str = "long") -> dict[str, dict[str, Any]]:
    root = _entries_by_market.get(market)
    if root is None:
        root = {}
        _entries_by_market[market] = root
    bucket = root.get(side)
    if bucket is None:
        bucket = {}
        root[side] = bucket
    return bucket


def invalidate(market: str | None = None, side: str | None = None) -> None:
    with _lock:
        if market is None:
            _entries_by_market.clear()
            return
        if side is None:
            _entries_by_market.pop(market, None)
            return
        root = _entries_by_market.get(market)
        if root is not None:
            root.pop(side, None)


def has_entry(include: str = "pass", market: str = "us", side: str = "long") -> bool:
    key = "all" if include == "all" else "pass"
    with _lock:
        return key in _bucket(market, side)


def get_cached_snapshot(market: str = "us", side: str = "long") -> dict | None:
    """Return the in-process snapshot held by a warm cache entry, if any."""
    with _lock:
        bucket = _bucket(market, side)
        for key in ("pass", "all"):
            entry = bucket.get(key)
            if entry is not None and entry.get("snapshot") is not None:
                return entry["snapshot"]
    return None


def try_warm_response(
    *,
    include: str = "pass",
    refresh: dict,
    stale: bool,
    accept_encoding: str | None = None,
    market: str = "us",
    side: str = "long",
) -> Response | None:
    """Serve prebuilt bytes when cache is warm — no SQLite / prepare_snapshot.

    For include=all with only pass cached, rebuild all from the in-process
    snapshot already held by the pass entry.
    """
    key = "all" if include == "all" else "pass"
    with _lock:
        bucket = _bucket(market, side)
        entry = bucket.get(key)
        snap = None
        if entry is not None:
            snap = entry.get("snapshot")
        if snap is None:
            pass_entry = bucket.get("pass")
            if pass_entry is not None:
                snap = pass_entry.get("snapshot")
    if snap is None and entry is None:
        return None
    if entry is None and key == "all" and snap is not None:
        entry = _rebuild_all(snap, refresh, stale, market=market, side=side)
    if entry is None and key == "pass" and snap is not None:
        rebuild(snap, refresh, stale, market=market, side=side)
        with _lock:
            entry = _bucket(market, side).get("pass")
    if entry is None:
        return None
    with _lock:
        raw, compressed = _with_live_fields(entry, refresh, stale)
    wants_gzip = accept_encoding is not None and "gzip" in accept_encoding.lower()
    if wants_gzip:
        return Response(
            content=compressed,
            media_type="application/json",
            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
        )
    return Response(content=raw, media_type="application/json", headers={"Vary": "Accept-Encoding"})


def _slim_row(row: dict) -> dict:
    item = dict(row)
    for key in _SLIM_DROP:
        item.pop(key, None)
    return item


def _view_rows(snapshot: dict, side: str) -> list:
    if side == "short":
        return list(snapshot.get("rowsShort") or [])
    return list(snapshot.get("rows") or [])


def _view_meta(snapshot: dict, side: str) -> dict:
    meta = dict(snapshot.get("meta") or {})
    meta["side"] = "short" if side == "short" else "long"
    if side == "short" and meta.get("summaryShort") is not None:
        meta["summary"] = meta["summaryShort"]
    return meta


def _build_payload(
    snapshot: dict,
    *,
    include_all: bool,
    refresh: dict,
    stale: bool,
    market: str = "us",
    side: str = "long",
) -> dict:
    rows = _view_rows(snapshot, side)
    if include_all:
        slim = [_slim_row(row) for row in rows]
    else:
        slim = [_slim_row(row) for row in rows if row.get("passHard")]
    # Serve-time merge so old HK snapshots still get TC short names after redeploy.
    if market == "hk":
        try:
            from app.universe_hk import apply_name_zh

            apply_name_zh(slim)
        except Exception:
            log.exception("HK nameZh serve-time merge failed")
    return {
        "ready": True,
        "stale": stale,
        "meta": _view_meta(snapshot, side),
        "rows": slim,
        "refresh": refresh,
    }


def _encode(payload: dict) -> tuple[bytes, bytes]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=_GZIP_LEVEL)
    return raw, compressed


def rebuild(snapshot: dict | None, refresh: dict, stale: bool, market: str = "us", side: str = "long") -> None:
    """Rebuild default (passHard) wire cache; drop include=all until requested.

    Rebuilding the long cache drops short bytes so the two sides cannot mix after
    a snapshot write. The next short request rebuilds from ``rowsShort``.
    """
    if snapshot is None:
        invalidate(market=market, side=side if side == "short" else None)
        return
    pass_payload = _build_payload(
        snapshot, include_all=False, refresh=refresh, stale=stale, market=market, side=side
    )
    pass_raw, pass_gz = _encode(pass_payload)
    with _lock:
        bucket = _bucket(market, side)
        bucket["pass"] = {
            "raw": pass_raw,
            "gzip": pass_gz,
            "refresh": dict(refresh),
            "stale": stale,
            "snapshot": snapshot,
        }
        # Full-universe bytes are large; rebuild lazily on ?include=all.
        bucket.pop("all", None)
        if side == "long":
            root = _entries_by_market.get(market)
            if root is not None:
                root.pop("short", None)
    log.info(
        "screen cache rebuilt pass_rows=%s pass_gzip=%sB",
        len(pass_payload["rows"]),
        len(pass_gz),
    )


def _rebuild_all(snapshot: dict, refresh: dict, stale: bool, market: str = "us", side: str = "long") -> dict[str, object]:
    all_payload = _build_payload(snapshot, include_all=True, refresh=refresh, stale=stale, market=market, side=side)
    all_raw, all_gz = _encode(all_payload)
    entry = {
        "raw": all_raw,
        "gzip": all_gz,
        "refresh": dict(refresh),
        "stale": stale,
        "snapshot": snapshot,
    }
    with _lock:
        _bucket(market, side)["all"] = entry
    log.info("screen cache rebuilt all_rows=%s all_gzip=%sB", len(all_payload["rows"]), len(all_gz))
    return entry


def _ensure(
    snapshot: dict | None,
    refresh: dict,
    stale: bool,
    include: str,
    market: str = "us",
    side: str = "long",
) -> dict[str, Any] | None:
    key = "all" if include == "all" else "pass"
    with _lock:
        entry = _bucket(market, side).get(key)
    if entry is not None:
        return entry
    if snapshot is None:
        return None
    if key == "pass":
        rebuild(snapshot, refresh, stale, market=market, side=side)
        with _lock:
            return _bucket(market, side).get("pass")
    return _rebuild_all(snapshot, refresh, stale, market=market, side=side)


def _with_live_fields(entry: dict[str, Any], refresh: dict, stale: bool) -> tuple[bytes, bytes]:
    """Reuse cached bytes when refresh/stale match; otherwise patch JSON and gzip level 1."""
    if entry.get("refresh") == refresh and entry.get("stale") is stale:
        return entry["raw"], entry["gzip"]
    payload = json.loads(entry["raw"])
    payload["refresh"] = refresh
    payload["stale"] = stale
    raw, compressed = _encode(payload)
    # Update cache so subsequent polls during idle reuse bytes.
    entry["raw"] = raw
    entry["gzip"] = compressed
    entry["refresh"] = dict(refresh)
    entry["stale"] = stale
    return raw, compressed


def response(
    *,
    snapshot: dict | None,
    refresh: dict,
    stale: bool,
    include: str = "pass",
    accept_encoding: str | None = None,
    market: str = "us",
    side: str = "long",
) -> Response:
    """Return a Response for /api/screen, serving pre-gzipped bytes when possible."""
    if snapshot is None:
        body = {
            "ready": False,
            "stale": False,
            "meta": None,
            "rows": [],
            "refresh": refresh,
        }
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return Response(content=raw, media_type="application/json")

    entry = _ensure(snapshot, refresh, stale, include, market=market, side=side)
    if entry is None:
        # Should not happen; fall back to building once.
        payload = _build_payload(
            snapshot, include_all=(include == "all"), refresh=refresh, stale=stale, market=market, side=side
        )
        raw, compressed = _encode(payload)
    else:
        with _lock:
            raw, compressed = _with_live_fields(entry, refresh, stale)

    wants_gzip = accept_encoding is not None and "gzip" in accept_encoding.lower()
    if wants_gzip:
        return Response(
            content=compressed,
            media_type="application/json",
            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
        )
    return Response(content=raw, media_type="application/json", headers={"Vary": "Accept-Encoding"})
