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
    return _detect_close_in_zone(bars, kind="support")


def detect_close_at_resistance(bars: list[dict]) -> tuple[bool, str | None, dict | None]:
    """Mirror of detect_close_at_support for structural resistance.

    Match = last close inside a resistance zone (swing highs + range highs + MA
    confluence, ≥2 touches, ±0.5×ATR). Prefers a close in the lower half of the
    zone (under the mid-line).
    """
    return _detect_close_in_zone(bars, kind="resistance")


def _detect_close_in_zone(bars: list[dict], *, kind: str) -> tuple[bool, str | None, dict | None]:
    if len(bars) < SWING_WINDOW * 2 + 40:
        return False, None, None

    supports, resistance, atr = compute_sr_clusters(bars)
    levels = supports if kind == "support" else resistance
    if atr is None or not levels:
        return False, None, None

    segment = bars[-SEGMENT:]
    last_close = float(segment[-1]["close"])
    if not last_close or last_close <= 0:
        return False, None, None

    candidates: list[tuple[int, float, int, dict]] = []
    for item in levels:
        level = float(item["price"])
        if level <= 0:
            continue
        half = zone_half_width(level, float(item.get("atr") or atr))
        zone_low = level - half
        zone_high = level + half
        if last_close < zone_low or last_close > zone_high:
            continue
        if kind == "support":
            # Prefer classic "sitting on support": close in upper half of zone, then nearest mid.
            prefer = 0 if last_close >= level else 1
        else:
            # Prefer "sitting under resistance": close in lower half of zone, then nearest mid.
            prefer = 0 if last_close <= level else 1
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
    label = "支持" if kind == "support" else "阻力"
    note = (
        f"收市近{label}約 {level:.2f}"
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
