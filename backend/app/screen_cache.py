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
# include -> {"raw": bytes, "gzip": bytes, "refresh": dict, "stale": bool}
_entries: dict[str, dict[str, Any]] = {}


def invalidate() -> None:
    with _lock:
        _entries.clear()


def has_entry(include: str = "pass") -> bool:
    key = "all" if include == "all" else "pass"
    with _lock:
        return key in _entries


def get_cached_snapshot() -> dict | None:
    """Return the in-process snapshot held by a warm cache entry, if any."""
    with _lock:
        for key in ("pass", "all"):
            entry = _entries.get(key)
            if entry is not None and entry.get("snapshot") is not None:
                return entry["snapshot"]
    return None


def try_warm_response(
    *,
    include: str = "pass",
    refresh: dict,
    stale: bool,
    accept_encoding: str | None = None,
) -> Response | None:
    """Serve prebuilt bytes when cache is warm — no SQLite / prepare_snapshot.

    For include=all with only pass cached, rebuild all from the in-process
    snapshot already held by the pass entry.
    """
    key = "all" if include == "all" else "pass"
    with _lock:
        entry = _entries.get(key)
        snap = None
        if entry is not None:
            snap = entry.get("snapshot")
        if snap is None:
            pass_entry = _entries.get("pass")
            if pass_entry is not None:
                snap = pass_entry.get("snapshot")
    if snap is None and entry is None:
        return None
    if entry is None and key == "all" and snap is not None:
        entry = _rebuild_all(snap, refresh, stale)
    if entry is None and key == "pass" and snap is not None:
        rebuild(snap, refresh, stale)
        with _lock:
            entry = _entries.get("pass")
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


def _build_payload(snapshot: dict, *, include_all: bool, refresh: dict, stale: bool) -> dict:
    rows = snapshot.get("rows") or []
    if include_all:
        slim = [_slim_row(row) for row in rows]
    else:
        slim = [_slim_row(row) for row in rows if row.get("passHard")]
    return {
        "ready": True,
        "stale": stale,
        "meta": snapshot.get("meta"),
        "rows": slim,
        "refresh": refresh,
    }


def _encode(payload: dict) -> tuple[bytes, bytes]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=_GZIP_LEVEL)
    return raw, compressed


def rebuild(snapshot: dict | None, refresh: dict, stale: bool) -> None:
    """Rebuild default (passHard) wire cache; drop include=all until requested."""
    if snapshot is None:
        invalidate()
        return
    pass_payload = _build_payload(snapshot, include_all=False, refresh=refresh, stale=stale)
    pass_raw, pass_gz = _encode(pass_payload)
    with _lock:
        _entries["pass"] = {
            "raw": pass_raw,
            "gzip": pass_gz,
            "refresh": dict(refresh),
            "stale": stale,
            "snapshot": snapshot,
        }
        # Full-universe bytes are large; rebuild lazily on ?include=all.
        _entries.pop("all", None)
    log.info(
        "screen cache rebuilt pass_rows=%s pass_gzip=%sB",
        len(pass_payload["rows"]),
        len(pass_gz),
    )


def _rebuild_all(snapshot: dict, refresh: dict, stale: bool) -> dict[str, object]:
    all_payload = _build_payload(snapshot, include_all=True, refresh=refresh, stale=stale)
    all_raw, all_gz = _encode(all_payload)
    entry = {
        "raw": all_raw,
        "gzip": all_gz,
        "refresh": dict(refresh),
        "stale": stale,
        "snapshot": snapshot,
    }
    with _lock:
        _entries["all"] = entry
    log.info("screen cache rebuilt all_rows=%s all_gzip=%sB", len(all_payload["rows"]), len(all_gz))
    return entry


def _ensure(snapshot: dict | None, refresh: dict, stale: bool, include: str) -> dict[str, Any] | None:
    key = "all" if include == "all" else "pass"
    with _lock:
        entry = _entries.get(key)
    if entry is not None:
        return entry
    if snapshot is None:
        return None
    if key == "pass":
        rebuild(snapshot, refresh, stale)
        with _lock:
            return _entries.get("pass")
    return _rebuild_all(snapshot, refresh, stale)


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

    entry = _ensure(snapshot, refresh, stale, include)
    if entry is None:
        # Should not happen; fall back to building once.
        payload = _build_payload(snapshot, include_all=(include == "all"), refresh=refresh, stale=stale)
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
