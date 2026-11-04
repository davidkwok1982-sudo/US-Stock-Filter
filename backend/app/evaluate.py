"""Turn one symbol's bars and quote into a Stage 2 row."""

from __future__ import annotations

from app.close_at_support import detect_close_at_support
from app.labels import group_labels, industry_zh, sector_zh
from app.metrics import (
    HIGH_DAYS,
    MICRO_CAP,
    MIN_MARKET_CAP,
    NEAR_HIGH_WITHIN,
    PENNY_PRICE,
    RS_DAYS_1W,
    RS_DAYS_3M,
    RS_DAYS_6M,
    SMA_FAST,
    SMA_MID,
    SMA_SLOW,
    average_dollar,
    build_score,
    is_otc,
    rolling_sma,
    sma_slope,
    window_return,
)

FAILS = {
    "ma_stack": "未呈價＞50＞150＞200",
    "ma_slope": "均線未全部向上",
    "cap": "市值不足20億美元或未明",
    "otc": "場外交易",
    "type": "非普通股",
}


def _closes(bars: list[dict]) -> dict[str, float]:
    return {bar["time"]: bar["close"] for bar in bars}


def evaluate(
    base: dict,
    bars: list[dict] | None,
    quote: dict | None,
    spy_bars: list[dict],
) -> dict:
    quote = quote or {}
    bars = bars or []
    closes = [bar["close"] for bar in bars]
    last_close = closes[-1] if closes else None
    price = quote.get("price") or last_close
    if price and last_close and last_close > 0 and abs(price - last_close) / last_close > 0.25:
        price = last_close

    sma50_series = rolling_sma(closes, SMA_FAST) if closes else []
    sma150_series = rolling_sma(closes, SMA_MID) if closes else []
    sma200_series = rolling_sma(closes, SMA_SLOW) if closes else []
    sma50 = sma50_series[-1] if sma50_series else None
    sma150 = sma150_series[-1] if sma150_series else None
    sma200 = sma200_series[-1] if sma200_series else None
    slope50 = sma_slope(sma50_series) if sma50_series else None
    slope150 = sma_slope(sma150_series) if sma150_series else None
    slope200 = sma_slope(sma200_series) if sma200_series else None

    high_window = bars[-HIGH_DAYS:] if bars else []
    high52 = max((bar["high"] for bar in high_window), default=None)
    low52 = min((bar["low"] for bar in high_window), default=None)

    dollar = average_dollar(bars) if bars else None
    dollar_basis = "63d" if dollar is not None else None
    avg_volume = quote.get("avgVolume3m")
    if dollar is None and price and avg_volume:
        dollar = price * avg_volume
        dollar_basis = "quote3m"

    spy_closes = _closes(spy_bars)
    spy_dates = [bar["time"] for bar in spy_bars]
    stock_closes = _closes(bars)
    ret1w = window_return(stock_closes, spy_dates or list(stock_closes), RS_DAYS_1W) if stock_closes else None
    ret3 = window_return(stock_closes, spy_dates or list(stock_closes), RS_DAYS_3M) if stock_closes else None
    ret6 = window_return(stock_closes, spy_dates or list(stock_closes), RS_DAYS_6M) if stock_closes else None
    spy_ret1w = window_return(spy_closes, spy_dates, RS_DAYS_1W) if spy_closes else None
    spy_ret3 = window_return(spy_closes, spy_dates, RS_DAYS_3M) if spy_closes else None
    spy_ret6 = window_return(spy_closes, spy_dates, RS_DAYS_6M) if spy_closes else None
    rs1w = ret1w - spy_ret1w if ret1w is not None and spy_ret1w is not None else None
    rs3 = ret3 - spy_ret3 if ret3 is not None and spy_ret3 is not None else None
    rs6 = ret6 - spy_ret6 if ret6 is not None and spy_ret6 is not None else None

    change = quote.get("changePct")
    if change is None and price and len(closes) >= 2 and closes[-2] > 0:
        change = price / closes[-2] - 1

    distance200 = price / sma200 - 1 if price and sma200 else None
    distance50 = price / sma50 - 1 if price and sma50 else None
    drawdown = None
    if price and high52:
        drawdown = price / high52 - 1

    exchange = quote.get("exchange")
    exchange_name = quote.get("exchangeName")
    otc = is_otc(exchange, exchange_name)
    quote_type = quote.get("quoteType")
    sector_en = base.get("sector") or quote.get("sector")
    industry_en = base.get("industry") or quote.get("industry")

    fail_codes: list[str] = []
    stack_ok = (
        price is not None
        and sma50 is not None
        and sma150 is not None
        and sma200 is not None
        and price > sma50 > sma150 > sma200
    )
    if not stack_ok:
        fail_codes.append("ma_stack")
    slopes_ok = (
        slope50 is not None
        and slope50 > 0
        and slope150 is not None
        and slope150 > 0
        and slope200 is not None
        and slope200 > 0
    )
    if not slopes_ok:
        fail_codes.append("ma_slope")
    market_cap = quote.get("marketCap")
    if market_cap is None or market_cap < MIN_MARKET_CAP:
        fail_codes.append("cap")
    if otc:
        fail_codes.append("otc")
    if quote_type and quote_type != "EQUITY":
        fail_codes.append("type")

    micro = bool(
        otc
        or (market_cap is not None and market_cap < MICRO_CAP)
        or (price is not None and price < PENNY_PRICE)
    )
    above50 = bool(price and sma50 and price > sma50)
    above200 = bool(price and sma200 and price > sma200)
    stacked = bool(stack_ok)
    slope_up = bool(slopes_ok)
    near_high = bool(drawdown is not None and drawdown >= -NEAR_HIGH_WITHIN)
    close_at_support, close_at_support_note, close_at_support_level = detect_close_at_support(bars)
    score, parts = build_score(
        distance200=distance200,
        above50=above50,
        slope50=slope50,
        slope200=slope200,
        rs1w=rs1w,
        dollar=dollar,
    )
    groups = list(base.get("groups") or [])
    name = quote.get("name") or base.get("name") or base.get("symbol")
    incomplete = len(bars) < SMA_SLOW or sma200 is None

    return {
        "symbol": base["symbol"],
        "name": name,
        "exchange": exchange_name or exchange,
        "groups": groups,
        "groupLabels": group_labels(groups),
        "sector": sector_zh(sector_en),
        "sectorEn": sector_en,
        "industry": industry_zh(industry_en),
        "industryEn": industry_en,
        "price": _round(price),
        "changePct": change,
        "marketCap": market_cap,
        "dollarVolume": dollar,
        "dollarVolumeBasis": dollar_basis,
        "vsSma200": distance200,
        "vsSma50": distance50,
        "sma50": _round(sma50),
        "sma150": _round(sma150),
        "sma200": _round(sma200),
        "sma50Slope": slope50,
        "sma150Slope": slope150,
        "sma200Slope": slope200,
        "aboveSma50": above50,
        "aboveSma200": above200,
        "maStacked": stacked,
        "slopeUp": slope_up,
        "high52": _round(high52),
        "low52": _round(low52),
        "pctFromHigh": drawdown,
        "nearHigh": near_high,
        "closeAtSupport": close_at_support,
        "closeAtSupportNote": close_at_support_note,
        "closeAtSupportLevel": (
            round(close_at_support_level["price"], 2) if close_at_support_level else None
        ),
        "closeAtSupportTouches": (
            int(close_at_support_level["touches"]) if close_at_support_level else None
        ),
        "ret1w": ret1w,
        "ret3m": ret3,
        "ret6m": ret6,
        "rs1w": rs1w,
        "rs3m": rs3,
        "rs6m": rs6,
        "rsBeat": bool(rs1w is not None and rs1w > 0),
        "pe": quote.get("pe"),
        "score": score,
        "scoreParts": parts,
        "passHard": not fail_codes,
        "failReasons": [FAILS[code] for code in fail_codes],
        "failCodes": fail_codes,
        "microOrOtc": micro,
        "otc": otc,
        "incomplete": incomplete,
        "barsCount": len(bars),
    }


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4 if abs(value) < 1 else 2)


def spy_snapshot(spy_bars: list[dict]) -> dict:
    closes = _closes(spy_bars)
    dates = [bar["time"] for bar in spy_bars]
    price = spy_bars[-1]["close"] if spy_bars else None
    return {
        "symbol": "SPY",
        "price": _round(price),
        "marketDate": spy_bars[-1]["time"] if spy_bars else None,
        "ret1w": window_return(closes, dates, RS_DAYS_1W),
        "ret3m": window_return(closes, dates, RS_DAYS_3M),
        "ret6m": window_return(closes, dates, RS_DAYS_6M),
    }


def summarize(rows: list[dict]) -> dict:
    def has(code: str) -> int:
        return sum(1 for row in rows if code in row["failCodes"])

    passed = [row for row in rows if row["passHard"]]
    return {
        "universe": len(rows),
        "pass": len(passed),
        "incomplete": sum(1 for row in rows if row["incomplete"]),
        "failMaStack": has("ma_stack"),
        "failMaSlope": has("ma_slope"),
        "failSma200": has("ma_stack"),
        "failCap": has("cap"),
        "failLiquidity": 0,
        "failBeta": 0,
        "failOtc": has("otc"),
        "failType": has("type"),
        "microOrOtc": sum(1 for row in rows if row["microOrOtc"]),
    }
