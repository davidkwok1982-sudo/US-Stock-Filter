"""Stage 2 maths: moving averages, relative strength, and the rank score.

Thresholds follow publicly described Stage 2 filters.
"""

from __future__ import annotations

import math

MIN_MARKET_CAP = 2_000_000_000
MIN_DOLLAR_VOLUME = 30_000_000
MIN_BETA = 1.0
NEAR_HIGH_WITHIN = 0.25

SMA_ULTRA = 10
SMA_SHORT = 20
SMA_FAST = 50
SMA_MID = 150
SMA_SLOW = 200
SLOPE_LOOKBACK = 20
BETA_LOOKBACK = 90
BETA_MIN_OBS = 60
RS_DAYS_1W = 5
RS_DAYS_20 = 20
RS_DAYS_3M = 63
RS_DAYS_6M = 126
DOLLAR_DAYS = 63
HIGH_DAYS = 252
PENNY_PRICE = 5.0
MICRO_CAP = 300_000_000

# Bump when score parts / RS definition change so cached rows recompute.
SCORE_RULE_VERSION = 5

# Freed nearHigh(15)+beta(5)=20 → slope / vsSma200 / rs / liquidity.
SCORE_MAX = {
    "dist200": 20,
    "above50": 15,
    "slope50": 15,
    "slope200": 15,
    "rs1w": 25,
    "liquidity": 10,
}


def window_return(closes: dict[str, float], calendar: list[str], back: int) -> float | None:
    usable = [day for day in calendar if day in closes]
    if len(usable) <= back:
        return None
    start = closes[usable[-1 - back]]
    end = closes[usable[-1]]
    if start <= 0 or end <= 0:
        return None
    return end / start - 1


def beta_vs(
    stock: dict[str, float],
    market: dict[str, float],
    lookback: int = BETA_LOOKBACK,
    min_obs: int = BETA_MIN_OBS,
) -> float | None:
    dates = sorted(set(stock) & set(market))
    stock_rets: list[float] = []
    market_rets: list[float] = []
    for left, right in zip(dates, dates[1:]):
        a, b = stock[left], stock[right]
        m0, m1 = market[left], market[right]
        if min(a, b, m0, m1) <= 0:
            continue
        stock_rets.append(b / a - 1)
        market_rets.append(m1 / m0 - 1)
    if len(stock_rets) < min_obs:
        return None
    stock_rets = stock_rets[-lookback:]
    market_rets = market_rets[-lookback:]
    if len(stock_rets) < min_obs:
        return None
    count = len(stock_rets)
    mean_stock = sum(stock_rets) / count
    mean_market = sum(market_rets) / count
    variance = sum((value - mean_market) ** 2 for value in market_rets) / count
    if variance < 1e-12:
        return None
    covariance = sum(
        (left - mean_stock) * (right - mean_market)
        for left, right in zip(stock_rets, market_rets)
    ) / count
    beta = covariance / variance
    if beta != beta or abs(beta) > 8:
        return None
    return beta


def rolling_sma(values: list[float], window: int) -> list[float | None]:
    series: list[float | None] = [None] * len(values)
    if window <= 0 or len(values) < window:
        return series
    total = sum(values[:window])
    series[window - 1] = total / window
    for index in range(window, len(values)):
        total += values[index] - values[index - window]
        series[index] = total / window
    return series


def sma_slope(series: list[float | None], lookback: int = SLOPE_LOOKBACK) -> float | None:
    if len(series) <= lookback:
        return None
    now = series[-1]
    previous = series[-1 - lookback]
    if now is None or previous is None or previous == 0:
        return None
    return now / previous - 1


def average_dollar(bars: list[dict], days: int = DOLLAR_DAYS, min_obs: int = 40) -> float | None:
    window = bars[-days:]
    values = [bar["dollar"] for bar in window if bar.get("dollar") and bar["dollar"] > 0]
    if len(values) < min_obs:
        return None
    return sum(values) / len(values)


def points_distance(distance: float | None) -> int:
    if distance is None or distance <= 0:
        return 0
    if distance <= 0.30:
        return SCORE_MAX["dist200"]
    if distance <= 0.60:
        return 12
    return 5


def points_flag(ok: bool, points: int) -> int:
    return points if ok else 0


def points_near_high(drawdown: float | None) -> int:
    """Legacy helper kept for tests; no longer used in build_score."""
    if drawdown is None:
        return 0
    if drawdown >= -0.08:
        return 15
    if drawdown >= -0.15:
        return 12
    if drawdown >= -0.25:
        return 8
    if drawdown >= -0.40:
        return 3
    return 0


def points_rs(excess: float | None, maximum: int | None = None) -> int:
    """Score ~1-week excess return vs SPY.

    -5pp or worse → 0; flat → ~40% of max; +8pp or better → max.
    """
    ceiling = SCORE_MAX["rs1w"] if maximum is None else maximum
    if excess is None:
        return 0
    scaled = (excess + 0.05) / 0.13
    return int(max(0, min(ceiling, round(scaled * ceiling))))


def points_liquidity(dollar: float | None) -> int:
    if dollar is None or dollar <= 0:
        return 0
    ratio = dollar / MIN_DOLLAR_VOLUME
    raw = 4 + math.log2(ratio) * 2
    return int(max(0, min(SCORE_MAX["liquidity"], round(raw))))


def points_beta(beta: float | None) -> int:
    """Legacy helper kept for tests; no longer used in build_score."""
    if beta is None or beta < MIN_BETA:
        return 0
    if beta <= 1.6:
        return 5
    if beta <= 2.2:
        return 4
    return 2


def build_score(
    *,
    distance200: float | None,
    above50: bool,
    slope50: float | None,
    slope200: float | None,
    rs1w: float | None,
    dollar: float | None,
) -> tuple[int, list[dict]]:
    parts = [
        {
            "key": "dist200",
            "label": "與200天線的距離",
            "points": points_distance(distance200),
            "max": SCORE_MAX["dist200"],
        },
        {
            "key": "above50",
            "label": "站上50天線",
            "points": points_flag(above50, SCORE_MAX["above50"]),
            "max": SCORE_MAX["above50"],
        },
        {
            "key": "slope50",
            "label": "50天線向上",
            "points": points_flag(slope50 is not None and slope50 > 0, SCORE_MAX["slope50"]),
            "max": SCORE_MAX["slope50"],
        },
        {
            "key": "slope200",
            "label": "200天線向上",
            "points": points_flag(slope200 is not None and slope200 > 0, SCORE_MAX["slope200"]),
            "max": SCORE_MAX["slope200"],
        },
        {
            "key": "rs1w",
            "label": "一星期相對 SPY",
            "points": points_rs(rs1w),
            "max": SCORE_MAX["rs1w"],
        },
        {
            "key": "liquidity",
            "label": "流動性",
            "points": points_liquidity(dollar),
            "max": SCORE_MAX["liquidity"],
        },
    ]
    total = sum(part["points"] for part in parts)
    return min(100, total), parts



def is_otc(exchange: str | None, exchange_name: str | None) -> bool:
    blob = f"{exchange or ''} {exchange_name or ''}".upper()
    markers = ("OTC", "PINK", "PNK", "GREY", "OTCBB")
    return any(marker in blob for marker in markers)
