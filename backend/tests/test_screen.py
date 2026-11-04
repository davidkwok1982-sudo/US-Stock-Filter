"""Unit tests for Stage 2 maths, levels, notes, and the symbol-directory parser."""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.evaluate import evaluate
from app.levels import find_levels
from app.metrics import (
    SCORE_MAX,
    breadth,
    points_distance,
    points_liquidity,
    points_near_high,
    points_rs,
)
from app.notes import build_notes
from app import store
from app.universe import parse_nasdaq_listed, parse_other_listed, to_yahoo, _merge


def _bars(start: date, closes: list[float], volume: float = 2_000_000) -> list[dict]:
    day = start
    bars = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(
            {
                "time": day.isoformat(),
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": volume,
                "dollar": close * volume,
            }
        )
        day += timedelta(days=1)
    return bars


def _paired(n: int = 280):
    rng = random.Random(7)
    spy = 400.0
    stock = 80.0
    day = date(2024, 1, 2)
    spy_bars = []
    stock_bars = []
    for _ in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        market = rng.gauss(0.0005, 0.01)
        idiosyncratic = rng.gauss(0.0003, 0.008)
        spy *= 1 + market
        stock *= 1 + (1.45 * market + idiosyncratic)
        stamp = day.isoformat()

        def bar(price: float, shares: float) -> dict:
            return {
                "time": stamp,
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": shares,
                "dollar": price * shares,
            }

        spy_bars.append(bar(spy, 80_000_000))
        stock_bars.append(bar(stock, 4_000_000))
        day += timedelta(days=1)
    return stock_bars, spy_bars


def _uptrend_pair(n: int = 280):
    """Steady climb so price > SMA50 > SMA150 > SMA200 and all slopes > 0."""
    day = date(2024, 1, 2)
    spy = 400.0
    stock = 60.0
    spy_bars = []
    stock_bars = []
    for index in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        spy *= 1.0012
        stock *= 1.0035 + (0.0004 if index % 7 == 0 else 0.0)
        stamp = day.isoformat()

        def bar(price: float, shares: float) -> dict:
            return {
                "time": stamp,
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": shares,
                "dollar": price * shares,
            }

        spy_bars.append(bar(spy, 80_000_000))
        stock_bars.append(bar(stock, 4_000_000))
        day += timedelta(days=1)
    return stock_bars, spy_bars


def test_score_weights_sum_to_100():
    assert sum(SCORE_MAX.values()) == 100


def test_score_edges():
    assert points_rs(-0.05) == 0
    assert points_rs(0) == 10
    assert points_rs(0.08) == 25
    assert points_rs(None) == 0
    assert points_distance(0) == 0
    assert points_distance(0.1) == 20
    assert points_distance(0.8) == 5
    assert points_near_high(0) == 15
    assert points_near_high(-0.2) == 8
    assert points_near_high(-0.5) == 0
    assert points_liquidity(30_000_000) == 4
    assert points_liquidity(240_000_000) == 10


def test_breadth_bands():
    assert breadth(200)["tone"] == "bullish"
    assert breadth(100)["tone"] == "neutral"
    assert breadth(99)["tone"] == "cautious"


def test_uptrend_passes_stage_two():
    stock_bars, spy_bars = _uptrend_pair()
    quote = {
        "price": stock_bars[-1]["close"],
        "changePct": 0.01,
        "marketCap": 80_000_000_000,
        "avgVolume3m": 4_000_000,
        "pe": 28.0,
        "name": "Example Inc.",
        "exchange": "NMS",
        "exchangeName": "NasdaqGS",
        "quoteType": "EQUITY",
    }
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": "Information Technology", "industry": "Semiconductors"},
        stock_bars,
        quote,
        spy_bars,
    )
    assert row["passHard"] is True
    assert row["aboveSma200"] is True
    assert row["maStacked"] is True
    assert row["slopeUp"] is True
    assert row["sma150"] is not None
    assert row["price"] > row["sma50"] > row["sma150"] > row["sma200"]
    assert "beta" not in row
    assert "liquidity" not in row["failCodes"]
    assert row["sector"] == "資訊科技"
    assert row["industry"] == "半導體"
    assert row["score"] > 40
    assert "rs1w" in row
    assert row["rsBeat"] == (row["rs1w"] is not None and row["rs1w"] > 0)
    assert all(part["key"] not in {"nearHigh", "beta", "rs6"} for part in row["scoreParts"])
    assert any(part["key"] == "rs1w" for part in row["scoreParts"])
    assert row["failReasons"] == []


def test_low_liquidity_still_passes_hard_when_ma_and_cap_ok():
    stock_bars, spy_bars = _uptrend_pair()
    # Tiny dollar volume — previously a hard fail; now soft (score only).
    for bar in stock_bars:
        bar["volume"] = 100
        bar["dollar"] = bar["close"] * 100
    quote = {
        "price": stock_bars[-1]["close"],
        "marketCap": 80_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NasdaqGS",
        "avgVolume3m": 100,
    }
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": None, "industry": None},
        stock_bars,
        quote,
        spy_bars,
    )
    assert row["passHard"] is True
    assert "liquidity" not in row["failCodes"]
    assert "beta" not in row["failCodes"]
    assert "beta_missing" not in row["failCodes"]


def test_downtrend_fails_ma_stack():
    closes = [200 - index * 0.4 for index in range(260)]
    bars = _bars(date(2024, 1, 2), closes, volume=5_000_000)
    _, spy_bars = _paired()
    quote = {
        "price": bars[-1]["close"],
        "marketCap": 40_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NYSE",
    }
    row = evaluate(
        {"symbol": "DOWN", "name": "Down Co", "groups": ["us"], "sector": None, "industry": None},
        bars,
        quote,
        spy_bars,
    )
    assert row["passHard"] is False
    assert "ma_stack" in row["failCodes"]
    assert "ma_slope" in row["failCodes"]


def test_price_above_200_but_not_stacked_fails():
    closes = [80 + i * 0.3 for i in range(250)]
    peak = closes[-1]
    closes.extend([peak * (1 - 0.004 * i) for i in range(1, 21)])
    bars = _bars(date(2024, 1, 2), closes, volume=5_000_000)
    _, spy_bars = _uptrend_pair(n=len(closes) + 20)
    quote = {
        "price": bars[-1]["close"],
        "marketCap": 40_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NYSE",
    }
    row = evaluate(
        {"symbol": "MIX", "name": "Mixed", "groups": ["us"], "sector": None, "industry": None},
        bars,
        quote,
        spy_bars,
    )
    assert row["sma50"] is not None and row["sma150"] is not None and row["sma200"] is not None
    assert row["price"] > row["sma200"]
    assert not (row["price"] > row["sma50"] > row["sma150"] > row["sma200"])
    assert row["passHard"] is False
    assert "ma_stack" in row["failCodes"]


def test_notes_omit_disclaimer_and_beta():
    stock_bars, spy_bars = _uptrend_pair()
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": "Technology", "industry": "Software"},
        stock_bars,
        {"price": stock_bars[-1]["close"], "marketCap": 50e9, "quoteType": "EQUITY", "exchangeName": "NasdaqGS", "pe": 22},
        spy_bars,
    )
    row["revenueGrowth"] = 0.12
    levels = find_levels(stock_bars)
    notes = build_notes(row, levels)
    assert notes["disclaimer"] == ""
    assert "非投資建議" not in notes["disclaimer"]
    assert "貝他" not in " ".join(notes["technical"])
    assert 2 <= len(notes["technical"]) <= 4
    assert 1 <= len(notes["fundamental"]) <= 2
    joined = " ".join(notes["technical"] + notes["fundamental"])
    assert "買入" not in joined


def test_support_sits_below_and_resistance_above():
    closes = []
    for index in range(160):
        phase = index % 20
        closes.append(100 + phase * 2 if phase <= 10 else 120 - (phase - 10) * 2)
    closes[-1] = 110
    bars = _bars(date(2024, 6, 3), closes, volume=1_000_000)
    bars[-1]["close"] = 110
    bars[-1]["high"] = 112
    bars[-1]["low"] = 108
    levels = find_levels(bars, window=5)
    assert levels
    supports = [level for level in levels if level["kind"] == "support"]
    resistance = [level for level in levels if level["kind"] == "resistance"]
    assert supports
    assert resistance
    assert all(level["price"] < 110 for level in supports)
    assert all(level["price"] > 110 for level in resistance)


def test_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "market.sqlite")
    bars = _bars(date(2024, 1, 2), [10 + i * 0.1 for i in range(5)], volume=1000)
    snapshot = {"meta": {"refreshedAt": "2026-10-31T00:00:00+00:00"}, "rows": [{"symbol": "AAA"}]}
    store.save_refresh(snapshot, {"AAA": bars, "SPY": bars})
    loaded = store.load_snapshot()
    assert loaded is not None
    assert loaded["rows"][0]["symbol"] == "AAA"
    restored = store.load_chart("AAA")
    assert restored is not None
    assert restored[0]["time"] == bars[0]["time"]
    assert restored[-1]["close"] == round(bars[-1]["close"], 4 if bars[-1]["close"] < 1 else 2)
    store.save_fundamentals("AAA", {"sector": "Technology", "revenueGrowth": 0.1})
    fund = store.load_fundamentals("AAA")
    assert fund is not None
    assert fund["sector"] == "Technology"


def test_parse_nasdaq_and_other_listed_filters_adr_etf():
    nasdaq = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
SPY|SPDR S&P 500 ETF Trust|G|N|N|100|Y|N
AACG|ATA Creativity Global - American Depositary Shares|S|N|N|100|N|N
ASML|ASML Holding N.V. - New York Registry Shares|Q|N|N|100|N|N
ZZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
File Creation Time: 1104202607:00|||||||
"""
    other = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK-B
QQQ|Invesco QQQ Trust, Series 1|P|QQQ|Y|100|N|QQQ
BABA|Alibaba Group Holding Limited American Depositary Shares|N|BABA|N|100|N|BABA
TSM|Taiwan Semiconductor Manufacturing Company Ltd.|N|TSM|N|40|N|TSM
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
File Creation Time: 1104202607:00|||||||
"""
    nasdaq_rows = parse_nasdaq_listed(nasdaq)
    other_rows = parse_other_listed(other)
    symbols = {row["symbol"] for row in _merge(nasdaq_rows + other_rows)}
    assert "AAPL" in symbols
    assert "IBM" in symbols
    assert to_yahoo("BRK.B") == "BRK-B"
    assert "BRK-B" in symbols
    assert "SPY" not in symbols
    assert "QQQ" not in symbols
    assert "AACG" not in symbols
    assert "BABA" not in symbols
    assert "TSM" not in symbols
    assert "ASML" not in symbols
    assert "ZZZT" not in symbols


def _close_at_support_bars() -> list[dict]:
    closes: list[float] = []
    for _ in range(6):
        closes.extend([100.0, 101.5, 103.0, 105.0, 107.0, 105.5, 103.5, 102.0, 101.0, 100.2])
    closes.extend([102.0, 104.0, 106.0, 104.0, 102.0, 100.5])

    day = date(2025, 1, 2)
    bars = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        low = close - 0.4
        if abs(close - 100.0) < 0.05:
            low = 100.0
        bars.append(
            {
                "time": day.isoformat(),
                "open": close,
                "high": close + 0.6,
                "low": low,
                "close": close,
                "volume": 2_000_000,
                "dollar": close * 2_000_000,
            }
        )
        day += timedelta(days=1)

    bars[-1]["close"] = 100.6
    bars[-1]["low"] = 100.1
    bars[-1]["high"] = 101.2
    bars[-1]["open"] = 100.8
    return bars


def test_close_at_support_detects_synthetic_pattern():
    from app.close_at_support import detect_close_at_support

    bars = _close_at_support_bars()
    matched, note = detect_close_at_support(bars)
    assert matched is True
    assert note is not None


def test_close_at_support_false_when_far_above():
    from app.close_at_support import detect_close_at_support

    closes = [50 + i * 0.15 for i in range(200)]
    bars = _bars(date(2024, 1, 2), closes)
    matched, note = detect_close_at_support(bars)
    assert matched is False
    assert note is None


def test_close_at_support_false_when_clearly_broken():
    from app.close_at_support import detect_close_at_support

    bars = _close_at_support_bars()
    bars[-1]["close"] = 96.0
    bars[-1]["low"] = 95.5
    bars[-1]["high"] = 96.5
    matched, note = detect_close_at_support(bars)
    assert matched is False
    assert note is None


def test_evaluate_includes_close_at_support_flag():
    stock_bars, spy_bars = _uptrend_pair()
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": None, "industry": None},
        stock_bars,
        {"price": stock_bars[-1]["close"], "marketCap": 80e9, "quoteType": "EQUITY", "exchangeName": "NasdaqGS"},
        spy_bars,
    )
    assert "closeAtSupport" in row
    assert isinstance(row["closeAtSupport"], bool)
    assert "breakoutRetest" not in row
