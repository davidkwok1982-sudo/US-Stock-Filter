"""Detect when the latest daily close sits right at a swing support.

Educational heuristic only — not a trading signal. Tuned for a selective
but non-empty hit rate on a liquid US universe (tens of passHard names).
"""

from __future__ import annotations

RULE_VERSION = 1

_SEGMENT = 189
_SWING_WINDOW = 6
_CLUSTER_TOL = 0.012
# Close within this band of the chosen support counts as "at support".
_BAND_ABOVE = 0.012  # up to +1.2% above support
_BAND_BELOW = 0.010  # small pierce: up to -1.0% below
_BROKEN_BELOW = 0.018  # clearly broken if more than ~1.8% under support
_MIN_MULTI_AGE = 8  # multi-touch levels should span some time


def detect_close_at_support(bars: list[dict]) -> tuple[bool, str | None]:
    if len(bars) < _SWING_WINDOW * 2 + 40:
        return False, None

    segment = bars[-_SEGMENT:]
    n = len(segment)
    last_close = segment[-1]["close"]
    if not last_close or last_close <= 0:
        return False, None

    swing_lows = _swing_lows(segment, _SWING_WINDOW)
    if not swing_lows:
        return False, None

    clusters = _quality_supports(_cluster(swing_lows, _CLUSTER_TOL), n)
    if not clusters:
        return False, None

    # Prefer classic "sitting on support": nearest level at or below close,
    # allowing a small pierce within the band. Reject clearly broken levels.
    candidates: list[tuple[int, float, int, dict]] = []
    for cluster in clusters:
        level = cluster["price"]
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
        candidates.append((prefer, abs(dist), -cluster["touches"], cluster))

    if not candidates:
        return False, None

    candidates.sort()
    best = candidates[0][3]
    level = best["price"]
    note = f"收市近支持約 {level:.2f}（觸及 {best['touches']}）"
    return True, note


def _quality_supports(clusters: list[dict], bar_count: int) -> list[dict]:
    """Keep multi-touch levels or a clear single swing not glued to the right edge."""
    kept: list[dict] = []
    edge = bar_count - _SWING_WINDOW - 1
    for cluster in clusters:
        touches = cluster["touches"]
        first_i = cluster["first_index"]
        last_i = cluster["last_index"]
        if touches >= 2:
            if last_i - first_i >= _MIN_MULTI_AGE or touches >= 3:
                kept.append(cluster)
            continue
        # Clear swing low (window-confirmed); skip if still forming at the edge.
        if touches == 1 and last_i < edge:
            kept.append(cluster)
    return kept


def _swing_lows(bars: list[dict], window: int) -> list[tuple[int, float]]:
    count = len(bars)
    lows: list[tuple[int, float]] = []
    for index in range(window, count - window):
        low = bars[index]["low"]
        left = index - window
        right = index + window + 1
        if low <= min(bar["low"] for bar in bars[left:right]):
            lows.append((index, low))
    return lows


def _cluster(points: list[tuple[int, float]], tolerance: float) -> list[dict]:
    if not points:
        return []
    ordered = sorted(points, key=lambda item: item[1])
    groups: list[list[tuple[int, float]]] = [[ordered[0]]]
    for index, price in ordered[1:]:
        prices = [item[1] for item in groups[-1]]
        anchor = sorted(prices)[len(prices) // 2]
        if anchor and abs(price - anchor) / anchor <= tolerance:
            groups[-1].append((index, price))
        else:
            groups.append([(index, price)])
    clusters = []
    for group in groups:
        prices = sorted(item[1] for item in group)
        indexes = [item[0] for item in group]
        median = prices[len(prices) // 2]
        clusters.append(
            {
                "price": median,
                "touches": len(group),
                "first_index": min(indexes),
                "last_index": max(indexes),
            }
        )
    return clusters
