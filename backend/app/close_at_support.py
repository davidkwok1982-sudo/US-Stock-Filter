"""Detect when the latest daily close sits right at a swing support.

Educational heuristic only — not a trading signal. Tuned for a selective
but non-empty hit rate on a liquid US universe (tens of passHard names).

Swing window / clustering MUST match ``levels.find_levels`` (via ``swings``).
"""

from __future__ import annotations

from app.swings import CLUSTER_TOL, SEGMENT, SWING_WINDOW, cluster, swing_extrema

RULE_VERSION = 2

# Close within this band of the chosen support counts as "at support".
_BAND_ABOVE = 0.012  # up to +1.2% above support
_BAND_BELOW = 0.010  # small pierce: up to -1.0% below
_BROKEN_BELOW = 0.018  # clearly broken if more than ~1.8% under support
_MIN_MULTI_AGE = 8  # multi-touch levels should span some time


def detect_close_at_support(bars: list[dict]) -> tuple[bool, str | None, dict | None]:
    """Return (matched, note, flagged_level).

    ``flagged_level`` is ``{"price", "touches"}`` when matched, else ``None``.
    """
    if len(bars) < SWING_WINDOW * 2 + 40:
        return False, None, None

    segment = bars[-SEGMENT:]
    n = len(segment)
    last_close = segment[-1]["close"]
    if not last_close or last_close <= 0:
        return False, None, None

    swing_lows = swing_extrema(segment, window=SWING_WINDOW, kind="low")
    if not swing_lows:
        return False, None, None

    clusters = _quality_supports(cluster(swing_lows, CLUSTER_TOL), n)
    if not clusters:
        return False, None, None

    # Prefer classic "sitting on support": nearest level at or below close,
    # allowing a small pierce within the band. Reject clearly broken levels.
    candidates: list[tuple[int, float, int, dict]] = []
    for item in clusters:
        level = item["price"]
        if level <= 0:
            continue
        dist = last_close / level - 1
        if dist < -_BROKEN_BELOW:
            continue
        if dist < -_BAND_BELOW:
            continue
        if dist > _BAND_ABOVE:
            continue
        # Rank: support <= close first, then nearest, then more touches.
        prefer = 0 if dist >= 0 else 1
        candidates.append((prefer, abs(dist), -item["touches"], item))

    if not candidates:
        return False, None, None

    candidates.sort()
    best = candidates[0][3]
    level = best["price"]
    note = f"收市近支持約 {level:.2f}（觸及 {best['touches']}）"
    flagged = {"price": level, "touches": best["touches"]}
    return True, note, flagged


def _quality_supports(clusters: list[dict], bar_count: int) -> list[dict]:
    """Keep multi-touch levels or a clear single swing not glued to the right edge."""
    kept: list[dict] = []
    edge = bar_count - SWING_WINDOW - 1
    for item in clusters:
        touches = item["touches"]
        first_i = item["first_index"]
        last_i = item["last_index"]
        if touches >= 2:
            if last_i - first_i >= _MIN_MULTI_AGE or touches >= 3:
                kept.append(item)
            continue
        # Clear swing low (window-confirmed); skip if still forming at the edge.
        if touches == 1 and last_i < edge:
            kept.append(item)
    return kept
