"""Detect when the latest daily close sits inside a structural support zone.

Educational heuristic only — not a trading signal. Levels come from the same
``compute_sr_clusters`` path as the chart (structural swings + range highs/lows,
ATR bands, ≥2 touches, SMA 10/20/50/150/200 confluence).
"""

from __future__ import annotations

from app.levels import compute_sr_clusters
from app.swings import SEGMENT, SWING_WINDOW, zone_half_width

RULE_VERSION = 4


def detect_close_at_support(bars: list[dict]) -> tuple[bool, str | None, dict | None]:
    """Return (matched, note, flagged_level).

    ``flagged_level`` includes ``price``, ``touches``, ``zoneLow``, ``zoneHigh``,
    ``atr`` when matched, else ``None``. Match = last close inside the support zone.
    """
    if len(bars) < SWING_WINDOW * 2 + 40:
        return False, None, None

    supports, _resistance, atr = compute_sr_clusters(bars)
    if atr is None or not supports:
        return False, None, None

    segment = bars[-SEGMENT:]
    last_close = float(segment[-1]["close"])
    if not last_close or last_close <= 0:
        return False, None, None

    candidates: list[tuple[int, float, int, dict]] = []
    for item in supports:
        level = float(item["price"])
        if level <= 0:
            continue
        half = zone_half_width(level, float(item.get("atr") or atr))
        zone_low = level - half
        zone_high = level + half
        if last_close < zone_low or last_close > zone_high:
            continue
        # Prefer classic "sitting on support": close in upper half of zone, then nearest mid.
        prefer = 0 if last_close >= level else 1
        dist = abs(last_close - level) / level
        candidates.append((prefer, dist, -int(item["touches"]), item))

    if not candidates:
        return False, None, None

    candidates.sort()
    best = candidates[0][3]
    level = float(best["price"])
    half = zone_half_width(level, float(best.get("atr") or atr))
    zone_low = level - half
    zone_high = level + half
    note = (
        f"收市近支持約 {level:.2f}"
        f"（區間 {zone_low:.2f}–{zone_high:.2f}，觸及 {best['touches']}）"
    )
    flagged = {
        "price": level,
        "touches": int(best["touches"]),
        "zoneLow": zone_low,
        "zoneHigh": zone_high,
        "atr": float(best.get("atr") or atr),
    }
    return True, note, flagged
