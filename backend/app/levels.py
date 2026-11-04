"""Approximate support and resistance from recent swing highs and lows.

Swing window / clustering MUST match ``close_at_support`` (via ``swings``).
"""

from __future__ import annotations

from app.swings import CLUSTER_TOL, SEGMENT, SWING_WINDOW, cluster, swing_extrema


def find_levels(bars: list[dict], window: int = SWING_WINDOW) -> list[dict]:
    if len(bars) < window * 2 + 5:
        return []
    segment = bars[-SEGMENT:]
    highs = swing_extrema(segment, window=window, kind="high")
    lows = swing_extrema(segment, window=window, kind="low")

    last = segment[-1]["close"]
    lookback = bars[-252:] if len(bars) > 252 else bars
    high_52 = max(bar["high"] for bar in lookback) if lookback else None

    def choose(points: list[tuple[int, float]], kind: str) -> list[dict]:
        ranked = sorted(
            cluster(points, CLUSTER_TOL),
            key=lambda item: (item["touches"], item["lastIndex"]),
            reverse=True,
        )
        picked: list[dict] = []
        for item in ranked:
            price = item["price"]
            if kind == "support" and price >= last * 0.997:
                continue
            if kind == "resistance" and price <= last * 1.003:
                continue
            if any(abs(price - other["price"]) / price < 0.015 for other in picked):
                continue
            touches = item["touches"]
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


def merge_flagged_support(levels: list[dict], flagged: dict | None) -> list[dict]:
    """Ensure the close-at-support level appears on the chart even if not top-3."""
    if not flagged:
        return levels
    raw = flagged.get("price")
    if raw is None:
        return levels
    price = round(float(raw), 2)
    if price <= 0:
        return levels
    touches = int(flagged.get("touches") or 1)
    label = "收市近支持帶" if touches >= 3 else "收市近支持"

    supports = [dict(item) for item in levels if item["kind"] == "support"]
    resistance = [item for item in levels if item["kind"] == "resistance"]

    for item in supports:
        if abs(item["price"] - price) / price < 0.015:
            item["price"] = price
            item["touches"] = max(int(item.get("touches") or 1), touches)
            item["label"] = label
            return sorted(supports, key=lambda entry: -entry["price"]) + resistance

    supports.append(
        {
            "price": price,
            "kind": "support",
            "touches": touches,
            "label": label,
        }
    )
    # Keep flagged + up to 2 other supports (may exceed prior top-3).
    supports = sorted(supports, key=lambda entry: -entry["price"])
    flagged_item = next(item for item in supports if abs(item["price"] - price) / price < 1e-9)
    others = [item for item in supports if item is not flagged_item]
    picked = [flagged_item] + others[:2]
    return sorted(picked, key=lambda entry: -entry["price"]) + resistance
