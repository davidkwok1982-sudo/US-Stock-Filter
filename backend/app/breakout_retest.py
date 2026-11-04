"""Detect approximate breakout-of-resistance then retest-as-support patterns.

Educational heuristic only — not a trading signal. Tuned for a non-empty
hit rate on a liquid US universe while staying selective.
"""

from __future__ import annotations

# Lookback for swing detection (~9 months of daily bars).
_SEGMENT = 189
_SWING_WINDOW = 6
# Cluster swing highs within this relative gap.
_CLUSTER_TOL = 0.012
# Breakout: close this far above the resistance zone.
_BREAK_PCT = 0.008
# Prefer two closes above; one clear close still counts.
_MIN_CLOSES_ABOVE = 2
# Breakout must fall inside this many recent sessions.
_BREAKOUT_LOOKBACK = 55
# After breakout, retest low must come within this band of the level.
_RETEST_BAND = 0.018
# A decisive failed breakout: close this far below the level.
_FAIL_CLOSE_PCT = 0.012
# Prefer actionable setups: retest low within this many sessions.
_RETEST_RECENT = 20
# Current close must still hold above the level (small cushion).
_HOLD_PCT = 0.005
# If price has already run too far above without a completed retest nearby,
# skip — after a valid retest, allow up to this extension.
_MAX_EXTENSION = 0.10
# Resistance must have formed at least this many bars before breakout.
_MIN_LEVEL_AGE = 8
# Need at least this many swing-high touches in the cluster (1 is ok if clear).
_MIN_TOUCHES = 2


def detect_breakout_retest(bars: list[dict]) -> tuple[bool, str | None]:
    """Return (matched, short zh-Hant note) for daily OHLC bars."""
    if len(bars) < _SWING_WINDOW * 2 + 40:
        return False, None

    segment = bars[-_SEGMENT:]
    n = len(segment)
    last_i = n - 1
    last_close = segment[last_i]["close"]
    if not last_close or last_close <= 0:
        return False, None

    swing_highs = _swing_highs(segment, _SWING_WINDOW)
    if not swing_highs:
        return False, None

    clusters = _cluster(swing_highs, _CLUSTER_TOL)
    # Prefer stronger / more recent clusters first.
    clusters.sort(key=lambda c: (c["touches"], c["last_index"]), reverse=True)

    best: tuple[bool, str] | None = None
    for cluster in clusters:
        level = cluster["price"]
        if level <= 0:
            continue
        # Level should be near current price — not a distant ancient ceiling.
        if level < last_close * 0.90 or level > last_close * 1.02:
            continue

        result = _try_level(segment, level, cluster["first_index"], cluster["last_index"], cluster["touches"])
        if result is None:
            continue
        matched, note = result
        if matched:
            # Prefer the most recent retest among matches.
            if best is None or True:
                best = (True, note)
                # First successful (strongest cluster) is enough.
                break

    if best:
        return best
    return False, None


def _swing_highs(bars: list[dict], window: int) -> list[tuple[int, float]]:
    count = len(bars)
    highs: list[tuple[int, float]] = []
    for index in range(window, count - window):
        high = bars[index]["high"]
        left = index - window
        right = index + window + 1
        if high >= max(bar["high"] for bar in bars[left:right]):
            highs.append((index, high))
    return highs


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
    return [c for c in clusters if c["touches"] >= _MIN_TOUCHES]


def _try_level(
    bars: list[dict],
    level: float,
    level_first: int,
    level_last: int,
    touches: int,
) -> tuple[bool, str] | None:
    n = len(bars)
    last_i = n - 1
    last_close = bars[last_i]["close"]

    breakout_start = max(0, last_i - _BREAKOUT_LOOKBACK)
    # Resistance must exist before the breakout window starts, or at least
    # before the breakout bar itself.
    if level_last >= last_i - 3:
        # Level still being formed at the tip — not prior resistance.
        return None

    breakout_i = _find_breakout(bars, level, breakout_start, level_last)
    if breakout_i is None:
        return None
    if breakout_i - level_first < _MIN_LEVEL_AGE and touches < 2:
        return None
    # Ensure at least one contributing swing high is before breakout.
    if level_last >= breakout_i:
        # Recompute: only swings before breakout count as prior resistance.
        # If the cluster's last touch is after/at breakout, require first touch early.
        if level_first >= breakout_i - _MIN_LEVEL_AGE:
            return None

    # After breakout: no decisive close back below the level before/at retest.
    retest_i = _find_retest(bars, level, breakout_i + 1, last_i)
    if retest_i is None:
        return None

    # Failed breakout check on the path from breakout through retest and after.
    for i in range(breakout_i, last_i + 1):
        if bars[i]["close"] < level * (1 - _FAIL_CLOSE_PCT):
            return None

    # Retest should be recent enough to be actionable.
    if last_i - retest_i > _RETEST_RECENT:
        return None

    # Still holding above the retested level.
    if last_close < level * (1 - _HOLD_PCT):
        return None

    # Prefer not already extended too far after the retest.
    if last_close > level * (1 + _MAX_EXTENSION):
        return None

    note = f"約 {level:.2f} 阻力突破後回測"
    return True, note


def _find_breakout(bars: list[dict], level: float, start: int, level_last: int) -> int | None:
    """First index in [start, end] where close clears resistance; prefer 2 closes."""
    threshold = level * (1 + _BREAK_PCT)
    n = len(bars)
    # Breakout must be after the resistance formed.
    start = max(start, level_last + 1)
    for i in range(start, n):
        if bars[i]["close"] < threshold:
            continue
        # Count consecutive closes above threshold starting at i.
        streak = 0
        j = i
        while j < n and bars[j]["close"] >= threshold:
            streak += 1
            j += 1
        if streak >= _MIN_CLOSES_ABOVE:
            # Prefer two closes when available, but accept one clear close.
            if streak >= 2 or bars[i]["close"] >= level * (1 + 0.01):
                return i
            if streak >= 1:
                return i
    return None


def _find_retest(bars: list[dict], level: float, start: int, end: int) -> int | None:
    """Index of a pullback low that tags former resistance as support."""
    if start > end:
        return None
    lo = level * (1 - _RETEST_BAND)
    hi = level * (1 + _RETEST_BAND)
    # Prefer the most recent retest touch.
    found: int | None = None
    for i in range(start, end + 1):
        low = bars[i]["low"]
        # Must have pulled back into the band (not just riding above).
        if lo <= low <= hi:
            # Also require that the bar's close is not a decisive breakdown.
            if bars[i]["close"] >= level * (1 - _FAIL_CLOSE_PCT):
                found = i
        # Alternative: wick into band from above while close holds.
        elif low <= hi and bars[i]["close"] >= level * (1 - _HOLD_PCT) and low >= lo * 0.995:
            # Close still near/above; low tagged the zone.
            if low <= level * (1 + _RETEST_BAND):
                found = i
    return found
