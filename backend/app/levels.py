"""Approximate support and resistance from recent swing highs and lows."""

from __future__ import annotations


def _clusters(points: list[tuple[int, float]], tolerance: float = 0.012) -> list[dict]:
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
                "lastIndex": max(indexes),
            }
        )
    return clusters


def find_levels(bars: list[dict], window: int = 8) -> list[dict]:
    if len(bars) < window * 2 + 5:
        return []
    segment = bars[-189:]
    count = len(segment)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for index in range(window, count - window):
        high = segment[index]["high"]
        low = segment[index]["low"]
        left = index - window
        right = index + window + 1
        if high >= max(bar["high"] for bar in segment[left:right]):
            highs.append((index, high))
        if low <= min(bar["low"] for bar in segment[left:right]):
            lows.append((index, low))

    last = segment[-1]["close"]
    lookback = bars[-252:] if len(bars) > 252 else bars
    high_52 = max(bar["high"] for bar in lookback) if lookback else None

    def choose(points: list[tuple[int, float]], kind: str) -> list[dict]:
        ranked = sorted(
            _clusters(points),
            key=lambda item: (item["touches"], item["lastIndex"]),
            reverse=True,
        )
        picked: list[dict] = []
        for cluster in ranked:
            price = cluster["price"]
            if kind == "support" and price >= last * 0.997:
                continue
            if kind == "resistance" and price <= last * 1.003:
                continue
            if any(abs(price - item["price"]) / price < 0.015 for item in picked):
                continue
            touches = cluster["touches"]
            if kind == "support":
                label = "支持帶" if touches >= 3 else "支持"
            else:
                label = "阻力帶" if touches >= 3 else "阻力"
            picked.append(
                {
                    "price": round(price, 2),
                    "kind": kind,
                    "touches": touches,
                    "label": label,
                }
            )
            if len(picked) >= 3:
                break
        return picked

    levels = choose(lows, "support") + choose(highs, "resistance")
    if high_52 and high_52 > last * 1.004:
        if all(abs(high_52 - item["price"]) / high_52 > 0.015 for item in levels if item["kind"] == "resistance"):
            levels.append(
                {
                    "price": round(high_52, 2),
                    "kind": "resistance",
                    "touches": 1,
                    "label": "52週高位",
                }
            )
    supports = sorted((item for item in levels if item["kind"] == "support"), key=lambda item: -item["price"])
    resistance = sorted((item for item in levels if item["kind"] == "resistance"), key=lambda item: item["price"])
    return supports[:3] + resistance[:3]
