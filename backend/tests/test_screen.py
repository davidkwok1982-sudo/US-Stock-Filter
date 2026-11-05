"""Unit tests for Stage 2 maths, levels, notes, and the symbol-directory parser."""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.evaluate import FAILS, FAILS_SHORT, evaluate
from app.levels import find_levels
from app.metrics import (
    SCORE_MAX,
    SLOPE_LOOKBACK,
    build_score,
    points_distance,
    points_distance_below,
    points_liquidity,
    points_near_high,
    points_rs,
    points_rs_inverted,
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


def test_slope_lookback_is_about_one_week():
    assert SLOPE_LOOKBACK == 5


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
    assert "rs20" in row
    assert row["rsBeat"] == (row["rs1w"] is not None and row["rs1w"] > 0)
    assert row["rsBeat20"] == (row["rs20"] is not None and row["rs20"] > 0)
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


def test_price_below_sma50_fails_hard_when_ma_order_ok():
    """CRWD-style: price dipped under SMA50 while 50 > 150 > 200 and slopes up → fail ma_stack."""
    stock_bars, spy_bars = _uptrend_pair()
    last_close = stock_bars[-1]["close"]
    # Quote below SMA50 but within the 25% quote/last_close guard; MAs from closes stay stacked.
    quote_price = last_close * 0.90
    quote = {
        "price": quote_price,
        "marketCap": 80_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NasdaqGS",
        "avgVolume3m": 4_000_000,
    }
    row = evaluate(
        {"symbol": "CRWD", "name": "CrowdStrike", "groups": ["us"], "sector": None, "industry": None},
        stock_bars,
        quote,
        spy_bars,
    )
    assert row["sma50"] > row["sma150"] > row["sma200"]
    assert row["price"] < row["sma50"]
    assert row["maStacked"] is False
    assert row["passHard"] is False
    assert "ma_stack" in row["failCodes"]
    assert row["aboveSma50"] is False
    assert FAILS["ma_stack"] == "股價＞50＞150＞200"


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
    assert "過去約一星期" in " ".join(notes["technical"])
    assert "過去約一個月" not in " ".join(notes["technical"])
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


def test_industry_priority_includes_short_only_passers(tmp_path, monkeypatch):
    """Short heatmap needs profiles for names that fail the long Stage 2 gate."""
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    engine = Engine()
    rows = [
        {
            "symbol": "LONG",
            "passHard": True,
            "score": 90,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
        },
        {
            "symbol": "SHORTONLY",
            "passHard": False,
            "score": 5,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
        },
        {
            "symbol": "NEITHER",
            "passHard": False,
            "score": 1,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
        },
    ]
    short_rows = [
        {**rows[0], "passHard": False, "score": 2},
        {**rows[1], "passHard": True, "score": 88},
        {**rows[2], "passHard": False, "score": 1},
    ]
    priority = engine._industry_priority_rows(rows, short_rows)
    assert [row["symbol"] for row in priority] == ["LONG", "SHORTONLY"]
    snapshot = {"rows": rows, "rowsShort": short_rows}
    assert engine._needs_industry_backfill(snapshot) is True



def test_industry_priority_empty_when_no_passers(tmp_path, monkeypatch):
    """Do not fall back to the full universe — that would Yahoo-fetch thousands."""
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    engine = Engine()
    rows = [
        {"symbol": "A", "passHard": False, "score": 1, "industry": None, "industryEn": None, "sector": None, "sectorEn": None},
        {"symbol": "B", "passHard": False, "score": 1, "industry": None, "industryEn": None, "sector": None, "sectorEn": None},
    ]
    short_rows = [{**row, "passHard": False} for row in rows]
    assert engine._industry_priority_rows(rows, short_rows) == []
    assert engine._needs_industry_backfill({"rows": rows, "rowsShort": short_rows}) is False


def test_prepare_snapshot_defers_yahoo_industry_fetch(tmp_path, monkeypatch):
    """Screen hot path must not wait on assetProfile network calls."""
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    store_mod.init_db()
    engine = Engine()
    snapshot = {
        "meta": {"criteria": {}, "summary": {"pass": 1}, "universe": {"unique": 1, "evaluated": 1}},
        "rows": [
            {
                "symbol": "NEEDY",
                "passHard": True,
                "score": 80,
                "failCodes": [],
                "industry": None,
                "industryEn": None,
                "sector": None,
                "sectorEn": None,
                "closeAtSupport": False,
                "rs1w": 0.01,
                "rs20": 0.02,
            }
        ],
        "rowsShort": [],
    }
    store_mod.save_snapshot(snapshot)
    calls = []

    def fake_enrich(rows, *, fetch_missing=True, **kwargs):
        calls.append({"n": len(rows), "fetch_missing": fetch_missing})
        return 0

    started = []

    monkeypatch.setattr(engine, "_enrich_rows_with_profiles", fake_enrich)
    monkeypatch.setattr(engine, "start_industry_backfill", lambda: started.append(True) or True)
    # Skip unrelated backfills
    monkeypatch.setattr(engine, "_backfill_close_at_support", lambda snap: None)
    monkeypatch.setattr(engine, "_backfill_score_rules", lambda snap: None)

    out = engine.prepare_snapshot()
    assert out is not None
    assert calls and all(c["fetch_missing"] is False for c in calls)
    assert started == [True]


def test_sync_short_labels_copies_industry_onto_short_passers(tmp_path, monkeypatch):
    from app.engine import Engine
    from app import store as store_mod

    monkeypatch.setattr(store_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "market.sqlite")
    store_mod.init_db()
    store_mod.save_fundamentals(
        "WEAK", {"sector": "Energy", "industry": "Oil & Gas E&P"}
    )
    engine = Engine()
    long_rows = [
        {
            "symbol": "WEAK",
            "name": "Weak Co",
            "passHard": False,
            "score": 4,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
            "groups": ["us"],
            "groupLabels": ["美股"],
            "exchange": "NYSE",
            "pe": None,
        }
    ]
    short_rows = [
        {
            "symbol": "WEAK",
            "name": "Weak Co",
            "passHard": True,
            "score": 91,
            "sector": None,
            "sectorEn": None,
            "industry": None,
            "industryEn": None,
            "groups": ["us"],
            "groupLabels": ["美股"],
            "exchange": "NYSE",
            "pe": None,
        }
    ]
    filled = engine._enrich_rows_with_profiles(
        engine._industry_priority_rows(long_rows, short_rows),
        fetch_missing=False,
    )
    assert filled == 1
    assert long_rows[0]["industryEn"] == "Oil & Gas E&P"
    engine._sync_short_labels(long_rows, short_rows)
    assert short_rows[0]["industryEn"] == "Oil & Gas E&P"
    assert short_rows[0]["sectorEn"] == "Energy"
    assert short_rows[0]["industry"]
    assert short_rows[0]["sector"]


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


def test_screen_cache_warm_path_skips_rebuild(tmp_path, monkeypatch):
    """Warm pass entry serves gzip without needing a fresh prepare_snapshot."""
    import gzip
    import json

    from app import screen_cache

    screen_cache.invalidate()
    snapshot = {
        "meta": {"refreshedAt": "2026-11-05T00:00:00+00:00", "summary": {"passHard": 2}},
        "rows": [
            {"symbol": "AAA", "passHard": True, "score": 80, "scoreParts": [1], "beta": 1.1},
            {"symbol": "BBB", "passHard": False, "score": 10},
            {"symbol": "CCC", "passHard": True, "score": 70, "betaBasis": "x"},
        ],
    }
    refresh = {"running": False, "progress": 100, "message": "更新完成", "error": None}
    screen_cache.rebuild(snapshot, refresh, stale=False)
    assert screen_cache.has_entry("pass")
    assert screen_cache.get_cached_snapshot() is snapshot

    warm = screen_cache.try_warm_response(
        include="pass",
        refresh=refresh,
        stale=False,
        accept_encoding="gzip, deflate",
    )
    assert warm is not None
    assert warm.headers["content-encoding"] == "gzip"
    payload = json.loads(gzip.decompress(warm.body))
    assert payload["ready"] is True
    assert [row["symbol"] for row in payload["rows"]] == ["AAA", "CCC"]
    assert all("scoreParts" not in row and "beta" not in row for row in payload["rows"])

    # Live refresh patch during polling should not drop the entry.
    busy = {"running": True, "progress": 40, "message": "更新中", "error": None}
    warm2 = screen_cache.try_warm_response(
        include="pass", refresh=busy, stale=False, accept_encoding="gzip"
    )
    payload2 = json.loads(gzip.decompress(warm2.body))
    assert payload2["refresh"]["running"] is True
    assert len(payload2["rows"]) == 2

    assert screen_cache.try_warm_response(
        include="pass", refresh=busy, stale=False, accept_encoding=None
    ).headers.get("content-encoding") is None


def test_short_score_prefers_early_and_weaker_rs():
    near = build_score(
        distance200=-0.08,
        above50=False,
        below50=True,
        slope50=-0.01,
        slope200=-0.01,
        rs1w=-0.08,
        dollar=30_000_000,
        side="short",
    )[0]
    far = build_score(
        distance200=-0.9,
        above50=False,
        below50=True,
        slope50=-0.01,
        slope200=-0.01,
        rs1w=-0.08,
        dollar=30_000_000,
        side="short",
    )[0]
    assert near > far
    weak = build_score(
        distance200=-0.1,
        above50=False,
        below50=True,
        slope50=-0.01,
        slope200=-0.01,
        rs1w=-0.08,
        dollar=30_000_000,
        side="short",
    )[0]
    strong = build_score(
        distance200=-0.1,
        above50=False,
        below50=True,
        slope50=-0.01,
        slope200=-0.01,
        rs1w=0.08,
        dollar=30_000_000,
        side="short",
    )[0]
    assert weak > strong
    assert points_distance_below(-0.1) == 20
    assert points_distance_below(0.1) == 0
    assert points_rs_inverted(-0.08) == 25
    assert points_rs_inverted(0.05) == 0
    assert points_rs_inverted(0) == points_rs(0)
    long_score = build_score(
        distance200=0.1,
        above50=True,
        slope50=0.01,
        slope200=0.01,
        rs1w=0.08,
        dollar=30_000_000,
    )[0]
    assert long_score == 20 + 15 + 15 + 15 + 25 + 4


def test_downtrend_passes_short_gate_and_uptrend_fails():
    closes = [200 - index * 0.4 for index in range(260)]
    bars = _bars(date(2024, 1, 2), closes, volume=5_000_000)
    _, spy_bars = _paired()
    quote = {
        "price": bars[-1]["close"],
        "marketCap": 40_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NYSE",
    }
    base = {"symbol": "DOWN", "name": "Down Co", "groups": ["us"], "sector": None, "industry": None}
    short_row = evaluate(base, bars, quote, spy_bars, side="short")
    assert short_row["passHard"] is True
    assert short_row["price"] < short_row["sma50"] < short_row["sma150"] < short_row["sma200"]
    assert short_row["slopeDown"] is True
    assert short_row["slopeUp"] is False
    assert short_row["failReasons"] == []
    assert "ma_stack" not in short_row["failCodes"]
    assert FAILS_SHORT["ma_stack"] == "股價＜50＜150＜200"
    assert FAILS_SHORT["ma_slope"] == "均線未全部向下"

    stock_bars, spy_up = _uptrend_pair()
    up_quote = {
        "price": stock_bars[-1]["close"],
        "marketCap": 80_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NasdaqGS",
    }
    up_short = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["us"], "sector": None, "industry": None},
        stock_bars,
        up_quote,
        spy_up,
        side="short",
    )
    assert up_short["passHard"] is False
    assert "ma_stack" in up_short["failCodes"]
    assert "ma_slope" in up_short["failCodes"]
    assert "股價＜50＜150＜200" in up_short["failReasons"]
    assert "均線未全部向下" in up_short["failReasons"]

    # Same gates as the matching long market: HK floor still applies on the short side.
    tiny = evaluate(
        base,
        bars,
        {**quote, "marketCap": 5_000_000_000},
        spy_bars,
        side="short",
        min_market_cap=10_000_000_000,
        cap_fail_label="市值不足100億港元或未明",
    )
    assert tiny["passHard"] is False
    assert "cap" in tiny["failCodes"]
    assert tiny["failReasons"][-1] == "市值不足100億港元或未明" or "市值不足100億港元或未明" in tiny["failReasons"]


def test_long_fail_labels_unchanged():
    assert FAILS["ma_stack"] == "股價＞50＞150＞200"
    assert FAILS["ma_slope"] == "均線未全部向上"


def test_screen_cache_keeps_long_and_short_apart():
    import gzip
    import json

    from app import screen_cache

    screen_cache.invalidate()
    snapshot = {
        "meta": {
            "refreshedAt": "2026-11-05T00:00:00+00:00",
            "summary": {"pass": 1, "failMaStack": 1},
            "summaryShort": {"pass": 1, "failMaStack": 9},
        },
        "rows": [
            {"symbol": "LONG", "passHard": True, "score": 80},
            {"symbol": "NOPE", "passHard": False, "score": 1},
        ],
        "rowsShort": [
            {"symbol": "SHORT", "passHard": True, "score": 70},
            {"symbol": "STILL", "passHard": False, "score": 2},
        ],
    }
    refresh = {"running": False, "progress": 100, "message": "更新完成", "error": None}
    screen_cache.rebuild(snapshot, refresh, stale=False, market="us", side="long")
    screen_cache.rebuild(snapshot, refresh, stale=False, market="us", side="short")
    long_resp = screen_cache.try_warm_response(
        include="pass", refresh=refresh, stale=False, accept_encoding="gzip", market="us", side="long"
    )
    short_resp = screen_cache.try_warm_response(
        include="pass", refresh=refresh, stale=False, accept_encoding="gzip", market="us", side="short"
    )
    long_payload = json.loads(gzip.decompress(long_resp.body))
    short_payload = json.loads(gzip.decompress(short_resp.body))
    assert [row["symbol"] for row in long_payload["rows"]] == ["LONG"]
    assert [row["symbol"] for row in short_payload["rows"]] == ["SHORT"]
    assert long_payload["meta"]["side"] == "long"
    assert short_payload["meta"]["side"] == "short"
    assert short_payload["meta"]["summary"]["pass"] == 1
    assert short_payload["meta"]["summary"]["failMaStack"] == 9
    # Rebuilding long must drop the short bytes so a later short read cannot reuse them.
    screen_cache.rebuild(snapshot, refresh, stale=False, market="us", side="long")
    assert screen_cache.has_entry("pass", market="us", side="long")
    assert not screen_cache.has_entry("pass", market="us", side="short")


def test_close_at_resistance_mirrors_support_shape():
    from app.close_at_support import detect_close_at_resistance
    from app.levels import merge_flagged_resistance

    support_bars = _close_at_support_bars()
    # Reflect prices so the former support trough becomes a resistance ceiling.
    bars = []
    for bar in support_bars:
        reflected = {
            **bar,
            "open": round(200 - bar["open"], 4),
            "high": round(200 - bar["low"], 4),
            "low": round(200 - bar["high"], 4),
            "close": round(200 - bar["close"], 4),
        }
        bars.append(reflected)
    matched, note, flagged = detect_close_at_resistance(bars)
    assert matched is True
    assert note and note.startswith("收市近阻力")
    assert flagged is not None
    assert flagged["zoneLow"] <= bars[-1]["close"] <= flagged["zoneHigh"]
    levels = merge_flagged_resistance(find_levels(bars), flagged)
    resistance = [item for item in levels if item["kind"] == "resistance"]
    assert any(abs(item["price"] - flagged["price"]) / flagged["price"] < 0.02 for item in resistance)
