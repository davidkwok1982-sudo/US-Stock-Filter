"""Detect approximate breakout-of-resistance then retest-as-support patterns.

Educational heuristic only — not a trading signal. Tuned for a selective
but non-empty hit rate on a liquid US universe.
"""

from __future__ import annotations

# Bump when the rule changes so cached rows can be recomputed once.
RULE_VERSION = 2

_SEGMENT = 189
_SWING_WINDOW = 5
_CLUSTER_TOL = 0.01
# Clear breakout above prior resistance.
_BREAK_PCT = 0.012
_MIN_CLOSES_ABOVE = 2
_BREAKOUT_LOOKBACK = 50
# After breakout, price should have extended a bit before the pullback.
_MIN_EXTENSION_AFTER_BREAK = 0.02
# Retest: low tags the former resistance zone.
_RETEST_BAND = 0.015
_FAIL_CLOSE_PCT = 0.01
_RETEST_RECENT = 16
_HOLD_PCT = 0.005
_MAX_EXTENSION = 0.08
_MIN_LEVEL_AGE = 10
_MIN_TOUCHES = 2
# Prior resistance should sit a little below the last close (actionable).
_LEVEL_BELOW_MIN = 0.0
_LEVEL_BELOW_MAX = 0.08


def detect_breakout_retest(bars: list[dict]) -> tuple[bool, str | None]:
    """Return (matched, short zh-Hant note) for daily OHLC bars."""
    if len(bars) < _SWING_WINDOW * 2 + 50:
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
    clusters = [c for c in clusters if c["touches"] >= _MIN_TOUCHES]
    clusters.sort(key=lambda c: (c["touches"], c["last_index"]), reverse=True)

    for cluster in clusters:
        level = cluster["price"]
        if level <= 0:
            continue
        dist = last_close / level - 1
        if dist < _LEVEL_BELOW_MIN or dist > _LEVEL_BELOW_MAX:
            continue

        result = _try_level(
            segment, level, cluster["first_index"], cluster["last_index"], cluster["touches"]
        )
        if result is not None:
            return result

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
    return clusters


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

    if level_last >= last_i - 5:
        return None

    breakout_start = max(0, last_i - _BREAKOUT_LOOKBACK)
    breakout_i = _find_breakout(bars, level, breakout_start, level_last)
    if breakout_i is None:
        return None
    if level_first >= breakout_i - _MIN_LEVEL_AGE and touches < 3:
        return None
    if level_last >= breakout_i and level_first >= breakout_i - _MIN_LEVEL_AGE:
        return None

    post = bars[breakout_i : last_i + 1]
    peak = max(bar["high"] for bar in post)
    if peak < level * (1 + _MIN_EXTENSION_AFTER_BREAK):
        return None

    retest_i = _find_retest(bars, level, breakout_i + 1, last_i)
    if retest_i is None:
        return None

    for i in range(breakout_i, last_i + 1):
        if bars[i]["close"] < level * (1 - _FAIL_CLOSE_PCT):
            return None

    if last_i - retest_i > _RETEST_RECENT:
        return None

    if last_close < level * (1 - _HOLD_PCT):
        return None

    if last_close > level * (1 + _MAX_EXTENSION):
        return None

    pre = bars[max(0, breakout_i - 40) : breakout_i]
    closes_below = sum(1 for bar in pre if bar["close"] <= level * 1.002)
    if closes_below < 8:
        return None

    note = f"約 {level:.2f} 阻力突破後回測"
    return True, note


def _find_breakout(bars: list[dict], level: float, start: int, level_last: int) -> int | None:
    threshold = level * (1 + _BREAK_PCT)
    n = len(bars)
    start = max(start, level_last + 1)
    i = start
    while i < n:
        if bars[i]["close"] < threshold:
            i += 1
            continue
        streak = 0
        j = i
        while j < n and bars[j]["close"] >= threshold:
            streak += 1
            j += 1
        if streak >= _MIN_CLOSES_ABOVE:
            return i
        i = max(j, i + 1)
    return None


def _find_retest(bars: list[dict], level: float, start: int, end: int) -> int | None:
    if start > end:
        return None
    lo = level * (1 - _RETEST_BAND)
    hi = level * (1 + _RETEST_BAND)
    found: int | None = None
    for i in range(start, end + 1):
        low = bars[i]["low"]
        close = bars[i]["close"]
        if low < lo or low > hi:
            continue
        if close < level * (1 - _FAIL_CLOSE_PCT):
            continue
        found = i
    return found
