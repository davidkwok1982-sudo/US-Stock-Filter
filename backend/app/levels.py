"""Structural support and resistance with ATR zones + SMA confluence.

Uses the same primitives as ``close_at_support`` (via ``swings``).
SMA(10/20/50/150/200) strengthen nearby levels or appear when they act as structure.
"""

from __future__ import annotations

from app.swings import (
    MIN_TOUCH_SPAN,
    MIN_TOUCHES,
    SEGMENT,
    SWING_WINDOW,
    apply_ma_confluence,
    atr_last,
    cluster_by_atr,
    count_zone_approaches,
    enrich_clusters,
    latest_sma_anchors,
    structural_extrema,
    zone_half_width,
)


def compute_sr_clusters(bars: list[dict], window: int = SWING_WINDOW) -> tuple[list[dict], list[dict], float | None]:
    """Return (support_clusters, resistance_clusters, atr) before top-N trim.

    Structural swings + range highs/lows stay primary. Latest SMA(10/20/50/150/200)
    values strengthen nearby clusters and may appear as levels when they clear the
    same ATR-zone touch rules.
    """
    if len(bars) < window * 2 + 5:
        return [], [], None
    segment = bars[-SEGMENT:]
    atr = atr_last(segment)
    if atr is None:
        return [], [], None

    low_points = structural_extrema(segment, window=window, kind="low")
    high_points = structural_extrema(segment, window=window, kind="high")
    anchors = latest_sma_anchors(segment)

    supports = enrich_clusters(
        segment,
        cluster_by_atr(low_points, atr),
        kind="support",
        atr=atr,
    )
    resistance = enrich_clusters(
        segment,
        cluster_by_atr(high_points, atr),
        kind="resistance",
        atr=atr,
    )
    supports = apply_ma_confluence(
        segment, supports, kind="support", atr=atr, anchors=anchors
    )
    resistance = apply_ma_confluence(
        segment, resistance, kind="resistance", atr=atr, anchors=anchors
    )
    return supports, resistance, atr


def find_levels(bars: list[dict], window: int = SWING_WINDOW) -> list[dict]:
    supports_raw, resistance_raw, atr = compute_sr_clusters(bars, window=window)
    if atr is None:
        return []

    segment = bars[-SEGMENT:]
    last = float(segment[-1]["close"])
    lookback = bars[-252:] if len(bars) > 252 else bars
    high_52 = max(float(bar["high"]) for bar in lookback) if lookback else None

    def choose(clusters: list[dict], kind: str) -> list[dict]:
        ranked = sorted(
            clusters,
            key=lambda item: (
                int(item.get("maConfluence") or 0),
                item["touches"],
                item["lastIndex"],
            ),
            reverse=True,
        )
        picked: list[dict] = []
        for item in ranked:
            price = float(item["price"])
            if kind == "support" and price >= last * 0.997:
                continue
            if kind == "resistance" and price <= last * 1.003:
                continue
            if any(abs(price - other["price"]) / price < 0.015 for other in picked):
                continue
            touches = int(item["touches"])
            if kind == "support":
                label = "支持帶" if touches >= 3 else "支持"
            else:
                label = "阻力帶" if touches >= 3 else "阻力"
            ma_window = item.get("maWindow")
            if ma_window:
                label = f"{label}（貼近{int(ma_window)}天線）"
            half = zone_half_width(price, float(item.get("atr") or atr))
            entry = {
                "price": round(price, 2),
                "kind": kind,
                "touches": touches,
                "label": label,
                "zoneLow": round(price - half, 2),
                "zoneHigh": round(price + half, 2),
                "atr": round(float(item.get("atr") or atr), 4),
            }
            if ma_window:
                entry["maWindow"] = int(ma_window)
                entry["maConfluence"] = 1
            picked.append(entry)
            if len(picked) >= 3:
                break
        return picked

    levels = choose(supports_raw, "support") + choose(resistance_raw, "resistance")

    # 52-week high only if zone approaches already qualify (≥2) via enrich path.
    if high_52 and high_52 > last * 1.004 and atr:
        half = zone_half_width(high_52, atr)
        touches, first_i, last_i = count_zone_approaches(
            segment, high_52, kind="resistance", half_width=half
        )
        far = all(
            abs(high_52 - item["price"]) / high_52 > 0.015
            for item in levels
            if item["kind"] == "resistance"
        )
        if (
            far
            and touches >= MIN_TOUCHES
            and (last_i - first_i >= MIN_TOUCH_SPAN or touches >= 3)
        ):
            levels.append(
                {
                    "price": round(high_52, 2),
                    "kind": "resistance",
                    "touches": touches,
                    "label": "52週高位",
                    "zoneLow": round(high_52 - half, 2),
                    "zoneHigh": round(high_52 + half, 2),
                    "atr": round(atr, 4),
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
    touches = int(flagged.get("touches") or 2)
    label = "收市近支持帶" if touches >= 3 else "收市近支持"
    atr = flagged.get("atr")
    zone_low = flagged.get("zoneLow")
    zone_high = flagged.get("zoneHigh")
    if zone_low is None or zone_high is None:
        if atr:
            half = zone_half_width(price, float(atr))
            zone_low = round(price - half, 2)
            zone_high = round(price + half, 2)
        else:
            zone_low = price
            zone_high = price

    supports = [dict(item) for item in levels if item["kind"] == "support"]
    resistance = [item for item in levels if item["kind"] == "resistance"]

    for item in supports:
        if abs(item["price"] - price) / price < 0.015:
            item["price"] = price
            item["touches"] = max(int(item.get("touches") or 1), touches)
            item["label"] = label
            item["zoneLow"] = round(float(zone_low), 2)
            item["zoneHigh"] = round(float(zone_high), 2)
            if atr is not None:
                item["atr"] = round(float(atr), 4)
            return sorted(supports, key=lambda entry: -entry["price"]) + resistance

    supports.append(
        {
            "price": price,
            "kind": "support",
            "touches": touches,
            "label": label,
            "zoneLow": round(float(zone_low), 2),
            "zoneHigh": round(float(zone_high), 2),
            "atr": round(float(atr), 4) if atr is not None else None,
        }
    )
    supports = sorted(supports, key=lambda entry: -entry["price"])
    flagged_item = next(item for item in supports if abs(item["price"] - price) / price < 1e-9)
    others = [item for item in supports if item is not flagged_item]
    picked = [flagged_item] + others[:2]
    return sorted(picked, key=lambda entry: -entry["price"]) + resistance
