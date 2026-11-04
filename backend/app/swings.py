"""Shared swing high/low detection and clustering for support/resistance."""

from __future__ import annotations

SEGMENT = 189
SWING_WINDOW = 8
CLUSTER_TOL = 0.012


def swing_extrema(
    bars: list[dict],
    *,
    window: int = SWING_WINDOW,
    kind: str,
) -> list[tuple[int, float]]:
    """Return (index, price) swing highs or lows inside bars."""
    count = len(bars)
    if count < window * 2 + 1:
        return []
    points: list[tuple[int, float]] = []
    for index in range(window, count - window):
        left = index - window
        right = index + window + 1
        if kind == "high":
            high = bars[index]["high"]
            if high >= max(bar["high"] for bar in bars[left:right]):
                points.append((index, high))
        else:
            low = bars[index]["low"]
            if low <= min(bar["low"] for bar in bars[left:right]):
                points.append((index, low))
    return points


def cluster(points: list[tuple[int, float]], tolerance: float = CLUSTER_TOL) -> list[dict]:
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
                "lastIndex": max(indexes),
            }
        )
    return clusters
