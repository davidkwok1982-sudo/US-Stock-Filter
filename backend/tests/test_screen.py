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
    """Synthetic multi-touch support near 100 that survives swing window=8."""
    closes: list[float] = []
    # Rise-fall cycles with a clear trough at 100, spaced > 2*window apart.
    cycle = [100.0, 101.0, 102.5, 104.0, 106.0, 108.0, 107.0, 105.5, 104.0, 103.0, 102.0, 101.2, 100.8, 100.4, 100.2, 100.1, 100.0, 100.5, 101.5, 103.0]
    for _ in range(5):
        closes.extend(cycle)
    # Finish sitting just above support.
    closes.extend([101.0, 102.0, 103.0, 102.0, 101.0, 100.5])

    day = date(2025, 1, 2)
    bars = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        low = close - 0.35
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

    # Finish inside the ATR support zone around ~100 (not above zoneHigh).
    bars[-1]["close"] = 100.2
    bars[-1]["low"] = 99.8
    bars[-1]["high"] = 100.6
    bars[-1]["open"] = 100.0
    return bars


def test_close_at_support_detects_synthetic_pattern():
    from app.close_at_support import detect_close_at_support
    from app.levels import find_levels, merge_flagged_support
    from app.close_at_support import RULE_VERSION
    from app.swings import MIN_TOUCHES, ZONE_ATR_MULT

    bars = _close_at_support_bars()
    matched, note, flagged = detect_close_at_support(bars)
    assert matched is True
    assert note is not None
    assert flagged is not None
    assert flagged["price"] > 0
    assert flagged["touches"] >= MIN_TOUCHES
    assert flagged.get("zoneLow") is not None and flagged.get("zoneHigh") is not None
    assert flagged["zoneLow"] <= bars[-1]["close"] <= flagged["zoneHigh"]
    assert RULE_VERSION >= 3
    assert ZONE_ATR_MULT == 0.5
    levels = merge_flagged_support(find_levels(bars), flagged)
    supports = [item for item in levels if item["kind"] == "support"]
    assert any(abs(item["price"] - flagged["price"]) / flagged["price"] < 0.015 for item in supports)
    assert any(item.get("zoneLow") is not None for item in supports)


def test_close_at_support_false_when_far_above():
    from app.close_at_support import detect_close_at_support

    closes = [50 + i * 0.15 for i in range(200)]
    bars = _bars(date(2024, 1, 2), closes)
    matched, note, flagged = detect_close_at_support(bars)
    assert matched is False
    assert note is None
    assert flagged is None


def test_close_at_support_false_when_clearly_broken():
    from app.close_at_support import detect_close_at_support

    bars = _close_at_support_bars()
    bars[-1]["close"] = 96.0
    bars[-1]["low"] = 95.5
    bars[-1]["high"] = 96.5
    matched, note, flagged = detect_close_at_support(bars)
    assert matched is False
    assert note is None
    assert flagged is None




def test_close_at_support_ignores_weak_window6_only_swing():
    """PGNY fixture: weak/single 29.93 area must not become a ≥2-touch structural support."""
    import json
    from pathlib import Path

    from app.close_at_support import detect_close_at_support
    from app.levels import find_levels
    from app.swings import SWING_WINDOW, swing_extrema, SEGMENT

    bars = json.loads((Path(__file__).parent / "fixtures" / "pgny_daily.json").read_text())
    segment = bars[-SEGMENT:]
    lows6 = swing_extrema(segment, window=6, kind="low")
    lows8 = swing_extrema(segment, window=SWING_WINDOW, kind="low")
    assert any(abs(price - 29.93) < 0.01 for _, price in lows6)
    assert all(abs(price - 29.93) > 0.01 for _, price in lows8)

    matched, note, flagged = detect_close_at_support(bars)
    assert matched is False
    assert flagged is None
    supports = [item for item in find_levels(bars) if item["kind"] == "support"]
    assert all(abs(item["price"] - 29.93) > 0.05 for item in supports)



def test_merge_flagged_support_inserts_missing_level():
    from app.levels import merge_flagged_support

    levels = [
        {"price": 25.24, "kind": "support", "touches": 2, "label": "支持"},
        {"price": 33.0, "kind": "resistance", "touches": 1, "label": "阻力"},
    ]
    merged = merge_flagged_support(
        levels,
        {"price": 29.93, "touches": 2, "zoneLow": 29.2, "zoneHigh": 30.66, "atr": 1.46},
    )
    supports = [item for item in merged if item["kind"] == "support"]
    hit = next(item for item in supports if item["price"] == 29.93)
    assert hit["label"] == "收市近支持"
    assert hit["zoneLow"] == 29.2
    assert hit["zoneHigh"] == 30.66

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


def test_evaluate_uses_quote_sector_industry_when_base_empty():
    stock_bars, spy_bars = _uptrend_pair()
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": None, "industry": None},
        stock_bars,
        {
            "price": stock_bars[-1]["close"],
            "marketCap": 80e9,
            "quoteType": "EQUITY",
            "exchangeName": "NasdaqGS",
            "sector": "Healthcare",
            "industry": "Drug Manufacturers - General",
        },
        spy_bars,
    )
    assert row["sectorEn"] == "Healthcare"
    assert row["industryEn"] == "Drug Manufacturers - General"
    assert row["sector"]
    assert row["industry"]


def test_apply_profile_to_row_sets_zh_labels(tmp_path, monkeypatch):
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    engine = Engine()
    row = {"symbol": "LLY", "sector": None, "sectorEn": None, "industry": None, "industryEn": None}
    changed = engine._apply_profile_to_row(
        row, {"sector": "Healthcare", "industry": "Drug Manufacturers - General"}
    )
    assert changed is True
    assert row["sectorEn"] == "Healthcare"
    assert row["industryEn"] == "Drug Manufacturers - General"
    assert row["sector"] is not None
    assert row["industry"] is not None
    assert engine._row_needs_industry(row) is False


def test_enrich_rows_uses_fundamentals_cache(tmp_path, monkeypatch):
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    store_mod.init_db()
    store_mod.save_fundamentals(
        "MA", {"sector": "Financial Services", "industry": "Credit Services"}
    )
    engine = Engine()
    rows = [
        {
            "symbol": "MA",
            "passHard": True,
            "score": 80,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
        }
    ]
    filled = engine._enrich_rows_with_profiles(rows, fetch_missing=False)
    assert filled == 1
    assert rows[0]["sectorEn"] == "Financial Services"
    assert rows[0]["industryEn"] == "Credit Services"
    assert rows[0]["industry"]  # zh or passthrough


def test_levels_include_atr_zones_and_min_touches():
    from app.levels import find_levels
    from app.swings import MIN_TOUCHES

    bars = _close_at_support_bars()
    levels = find_levels(bars)
    assert levels
    for item in levels:
        assert item["touches"] >= MIN_TOUCHES
        assert item.get("zoneLow") is not None
        assert item.get("zoneHigh") is not None
        assert item["zoneLow"] < item["price"] < item["zoneHigh"] or item["zoneLow"] <= item["price"] <= item["zoneHigh"]


def test_ma_confluence_marks_nearby_support():
    """A structural support near the latest SMA gets maConfluence / maWindow."""
    from app.close_at_support import RULE_VERSION
    from app.levels import compute_sr_clusters, find_levels
    from app.swings import apply_ma_confluence, latest_sma_anchors

    assert RULE_VERSION == 4
    bars = _close_at_support_bars()
    supports, _resistance, atr = compute_sr_clusters(bars)
    assert atr is not None
    anchors = latest_sma_anchors(bars)
    assert any(a["window"] == 10 for a in anchors)
    assert any(a["window"] == 20 for a in anchors)

    # Force-mark confluence against a synthetic MA glued to the first support mid.
    if supports:
        glued = [{"window": 20, "price": float(supports[0]["price"])}]
        boosted = apply_ma_confluence(
            bars[-189:], supports, kind="support", atr=atr, anchors=glued
        )
        assert boosted[0].get("maConfluence") == 1
        assert boosted[0].get("maWindow") == 20

    levels = find_levels(bars)
    # Levels still carry ATR zones for filter; chart only draws mid.
    for item in levels:
        assert item.get("zoneLow") is not None
        assert item.get("zoneHigh") is not None
