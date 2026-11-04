"""Shared structural support/resistance primitives.

Filter「收市近支持」and chart levels MUST use the same helpers here
(via ``levels`` / ``close_at_support``), including SMA confluence anchors.
"""

from __future__ import annotations

SEGMENT = 189
SWING_WINDOW = 8
ATR_PERIOD = 14
ZONE_ATR_MULT = 0.5
CLUSTER_ATR_MULT = 0.75
MIN_TOUCHES = 2
MIN_TOUCH_SPAN = 5
RANGE_LOOKBACKS = (20, 60)
# Floor so quiet names still get a usable band.
MIN_ZONE_PCT = 0.003
# SMA periods folded into S/R confluence (chart + close-at-support share this).
SR_MA_WINDOWS = (10, 20, 50, 150, 200)


def atr_last(bars: list[dict], period: int = ATR_PERIOD) -> float | None:
    """Wilder ATR of the final bar; ``None`` if not enough history."""
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for index in range(1, len(bars)):
        high = float(bars[index]["high"])
        low = float(bars[index]["low"])
        prev_close = float(bars[index - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr if atr > 0 else None


def zone_half_width(price: float, atr: float) -> float:
    """Half-width of the S/R band (±0.5×ATR, floored)."""
    if price <= 0 or atr <= 0:
        return 0.0
    return max(ZONE_ATR_MULT * atr, price * MIN_ZONE_PCT)


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
                points.append((index, float(high)))
        else:
            low = bars[index]["low"]
            if low <= min(bar["low"] for bar in bars[left:right]):
                points.append((index, float(low)))
    return points


def range_extrema(bars: list[dict], kind: str) -> list[tuple[int, float]]:
    """Recent range highs/lows (e.g. ~20 / ~60 day) as structural anchors."""
    points: list[tuple[int, float]] = []
    count = len(bars)
    for lookback in RANGE_LOOKBACKS:
        if count < lookback:
            continue
        start = count - lookback
        window = bars[start:]
        if kind == "high":
            local = max(range(lookback), key=lambda i: window[i]["high"])
            points.append((start + local, float(window[local]["high"])))
        else:
            local = min(range(lookback), key=lambda i: window[i]["low"])
            points.append((start + local, float(window[local]["low"])))
    return points


def structural_extrema(
    bars: list[dict],
    *,
    window: int = SWING_WINDOW,
    kind: str,
) -> list[tuple[int, float]]:
    """Clear swings plus recent range highs/lows."""
    return swing_extrema(bars, window=window, kind=kind) + range_extrema(bars, kind)


def cluster_by_atr(
    points: list[tuple[int, float]],
    atr: float,
    *,
    mult: float = CLUSTER_ATR_MULT,
) -> list[dict]:
    """Group nearby structural prices; tolerance scales with ATR."""
    if not points or atr <= 0:
        return []
    ordered = sorted(points, key=lambda item: item[1])
    groups: list[list[tuple[int, float]]] = [[ordered[0]]]
    for index, price in ordered[1:]:
        prices = [item[1] for item in groups[-1]]
        anchor = sorted(prices)[len(prices) // 2]
        tol = max(mult * atr, anchor * MIN_ZONE_PCT)
        if abs(price - anchor) <= tol:
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
                "seed_touches": len(group),
                "first_index": min(indexes),
                "last_index": max(indexes),
                "lastIndex": max(indexes),
            }
        )
    return clusters


def count_zone_approaches(
    bars: list[dict],
    price: float,
    *,
    kind: str,
    half_width: float,
) -> tuple[int, int, int]:
    """Count distinct approaches where high/low enters the zone (runs count once)."""
    if price <= 0 or half_width <= 0:
        return 0, 0, 0
    lo = price - half_width
    hi = price + half_width
    touches = 0
    first = last = -1
    active = False
    for index, bar in enumerate(bars):
        if kind == "support":
            tip = float(bar["low"])
        else:
            tip = float(bar["high"])
        hit = lo <= tip <= hi
        if hit:
            if not active:
                touches += 1
                if first < 0:
                    first = index
            active = True
            last = index
        else:
            active = False
    if touches == 0:
        return 0, 0, 0
    return touches, first, last


def enrich_clusters(
    bars: list[dict],
    clusters: list[dict],
    *,
    kind: str,
    atr: float,
) -> list[dict]:
    """Re-score clusters with zone touch counts; keep ≥2 spaced approaches."""
    kept: list[dict] = []
    for item in clusters:
        price = float(item["price"])
        half = zone_half_width(price, atr)
        touches, first_i, last_i = count_zone_approaches(
            bars, price, kind=kind, half_width=half
        )
        if touches < MIN_TOUCHES:
            continue
        if last_i - first_i < MIN_TOUCH_SPAN and touches < 3:
            continue
        kept.append(
            {
                "price": price,
                "touches": touches,
                "first_index": first_i,
                "last_index": last_i,
                "lastIndex": last_i,
                "zoneLow": price - half,
                "zoneHigh": price + half,
                "atr": atr,
                "kind": kind,
            }
        )
    return kept


def latest_sma_anchors(bars: list[dict], windows: tuple[int, ...] = SR_MA_WINDOWS) -> list[dict]:
    """Latest SMA(close) values usable as S/R confluence anchors."""
    closes = [float(bar["close"]) for bar in bars]
    anchors: list[dict] = []
    for window in windows:
        if len(closes) < window:
            continue
        value = sum(closes[-window:]) / window
        if value > 0:
            anchors.append({"window": window, "price": value})
    return anchors


def apply_ma_confluence(
    bars: list[dict],
    clusters: list[dict],
    *,
    kind: str,
    atr: float,
    anchors: list[dict] | None = None,
) -> list[dict]:
    """Strengthen clusters near SMAs; add SMAs that themselves act as structure.

    ATR-zone touch rules are unchanged. Nearby MAs only boost ranking weight and
    may surface as levels when they independently clear MIN_TOUCHES.
    """
    if atr <= 0:
        return clusters
    if anchors is None:
        anchors = latest_sma_anchors(bars)
    if not anchors and not clusters:
        return clusters

    enriched = [dict(item) for item in clusters]
    claimed: set[int] = set()

    for item in enriched:
        price = float(item["price"])
        tol = max(CLUSTER_ATR_MULT * atr, price * MIN_ZONE_PCT)
        best_window = None
        best_dist = None
        for anchor in anchors:
            dist = abs(float(anchor["price"]) - price)
            if dist <= tol and (best_dist is None or dist < best_dist):
                best_dist = dist
                best_window = int(anchor["window"])
        if best_window is not None:
            item["maConfluence"] = 1
            item["maWindow"] = best_window
            claimed.add(best_window)

    for anchor in anchors:
        window = int(anchor["window"])
        if window in claimed:
            continue
        price = float(anchor["price"])
        if price <= 0:
            continue
        half = zone_half_width(price, atr)
        touches, first_i, last_i = count_zone_approaches(
            bars, price, kind=kind, half_width=half
        )
        if touches < MIN_TOUCHES:
            continue
        if last_i - first_i < MIN_TOUCH_SPAN and touches < 3:
            continue
        # Skip if still essentially the same mid as an existing cluster.
        if any(abs(price - float(item["price"])) <= max(CLUSTER_ATR_MULT * atr, price * MIN_ZONE_PCT) for item in enriched):
            continue
        enriched.append(
            {
                "price": price,
                "touches": touches,
                "first_index": first_i,
                "last_index": last_i,
                "lastIndex": last_i,
                "zoneLow": price - half,
                "zoneHigh": price + half,
                "atr": atr,
                "kind": kind,
                "maConfluence": 1,
                "maWindow": window,
            }
        )
    return enriched

