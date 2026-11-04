"""Unit tests for Stage 2 maths, levels, notes, and the constituent parser."""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.evaluate import evaluate
from app.levels import find_levels
from app.metrics import (
    SCORE_MAX,
    beta_vs,
    breadth,
    points_beta,
    points_distance,
    points_liquidity,
    points_near_high,
    points_rs,
)
from app.notes import DISCLAIMER, build_notes
from app import store
from app.universe import parse_constituents, to_yahoo


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


def test_score_weights_sum_to_100():
    assert sum(SCORE_MAX.values()) == 100


def test_score_edges():
    assert points_rs(-0.20) == 0
    assert points_rs(0) == 8
    assert points_rs(0.30) == 20
    assert points_rs(None) == 0
    assert points_distance(0) == 0
    assert points_distance(0.1) == 15
    assert points_distance(0.8) == 4
    assert points_near_high(0) == 15
    assert points_near_high(-0.2) == 8
    assert points_near_high(-0.5) == 0
    assert points_liquidity(30_000_000) == 4
    assert points_liquidity(240_000_000) == 10
    assert points_beta(0.9) == 0
    assert points_beta(1.2) == 5
    assert points_beta(2.5) == 2


def test_breadth_bands():
    assert breadth(200)["tone"] == "bullish"
    assert breadth(100)["tone"] == "neutral"
    assert breadth(99)["tone"] == "cautious"


def test_beta_recovers_planted_relationship():
    stock_bars, spy_bars = _paired()
    stock = {bar["time"]: bar["close"] for bar in stock_bars}
    spy = {bar["time"]: bar["close"] for bar in spy_bars}
    beta = beta_vs(stock, spy)
    assert beta is not None
    assert 1.05 < beta < 1.9


def test_uptrend_passes_stage_two():
    stock_bars, spy_bars = _paired()
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
        {"symbol": "EXM", "name": "Example", "groups": ["sp500"], "sector": "Information Technology", "industry": "Semiconductors"},
        stock_bars,
        quote,
        spy_bars,
    )
    assert row["passHard"] is True
    assert row["aboveSma200"] is True
    assert row["beta"] is not None and row["beta"] >= 1
    assert row["dollarVolume"] >= 30_000_000
    assert row["sector"] == "資訊科技"
    assert row["industry"] == "半導體"
    assert row["score"] > 40
    assert row["failReasons"] == []


def test_vendor_beta_is_preferred_over_the_90_day_estimate():
    stock_bars, spy_bars = _paired()
    quote = {
        "price": stock_bars[-1]["close"],
        "marketCap": 80_000_000_000,
        "quoteType": "EQUITY",
        "exchangeName": "NasdaqGS",
    }
    base = {"symbol": "EXM", "name": "Example", "groups": ["sp500"], "sector": None, "industry": None}
    low = evaluate(base, stock_bars, quote, spy_bars, vendor_beta=0.4)
    assert low["beta"] == 0.4
    assert low["betaBasis"] == "yahoo"
    assert "beta" in low["failCodes"]
    high = evaluate(base, stock_bars, quote, spy_bars, vendor_beta=1.2)
    assert high["betaBasis"] == "yahoo"
    assert "beta" not in high["failCodes"]
    assert "beta_missing" not in high["failCodes"]


def test_downtrend_fails_long_average():
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
        {"symbol": "DOWN", "name": "Down Co", "groups": ["sp400"], "sector": None, "industry": None},
        bars,
        quote,
        spy_bars,
    )
    assert row["passHard"] is False
    assert "sma200" in row["failCodes"]


def test_notes_include_disclaimer_and_bounds():
    stock_bars, spy_bars = _paired()
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["ndx"], "sector": "Technology", "industry": "Software"},
        stock_bars,
        {"price": stock_bars[-1]["close"], "marketCap": 50e9, "quoteType": "EQUITY", "exchangeName": "NasdaqGS", "pe": 22},
        spy_bars,
    )
    row["revenueGrowth"] = 0.12
    levels = find_levels(stock_bars)
    notes = build_notes(row, levels)
    assert DISCLAIMER in notes["disclaimer"]
    assert 2 <= len(notes["technical"]) <= 4
    assert 1 <= len(notes["fundamental"]) <= 2
    assert "非投資建議" in notes["disclaimer"]
    joined = " ".join(notes["technical"] + notes["fundamental"])
    assert "買入" not in joined
    assert "建議" not in joined or "非投資建議" in notes["disclaimer"]


def test_support_sits_below_and_resistance_above():
    closes = []
    for index in range(160):
        phase = index % 20
        closes.append(100 + phase * 2 if phase <= 10 else 120 - (phase - 10) * 2)
    closes[-1] = 110
    bars = _bars(date(2024, 6, 3), closes, volume=1_000_000)
    # Give the last bar a mid-range close without being a swing extreme.
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


def test_parse_wikipedia_styles_and_class_shares():
    sp = """
{| class="wikitable" id="constituents"
|-
! Symbol !! Security !! GICS Sector !! GICS Sub-Industry
|-
|| {{NyseSymbol|MMM}}
|| [[3M]]
|| Industrials
|| Industrial Conglomerates
|-
|| {{NyseSymbol|BRK.B}}
|| [[Berkshire Hathaway]]
|| Financials
|| Multi-Sector Holdings
|}
"""
    ndx = """
{| class="wikitable sortable" id="constituents"
|-
! Ticker !! Company !! ISIN !! ICB Industry !! ICB Subsector
|-
| AAPL || [[Apple Inc.]] || {{ISIN|sl=n|US0378331005}} || Technology || Computer Hardware
|-
| GOOG || [[Alphabet Inc.|Alphabet (Class C)]] || {{ISIN|sl=n|US02079K1079}} || Technology || Interactive Media & Services
|}
"""
    sp_rows = parse_constituents(sp, "sp500")
    ndx_rows = parse_constituents(ndx, "ndx")
    assert [row["symbol"] for row in sp_rows] == ["MMM", "BRK.B"]
    assert to_yahoo("BRK.B") == "BRK-B"
    assert sp_rows[0]["sector"] == "Industrials"
    assert sp_rows[0]["name"] == "3M"
    assert ndx_rows[0]["symbol"] == "AAPL"
    assert ndx_rows[1]["name"] == "Alphabet (Class C)"
    assert ndx_rows[1]["sector"] == "Technology"
    assert ndx_rows[1]["industry"] == "Interactive Media & Services"


def _close_at_support_bars() -> list[dict]:
    """Synthetic: repeated swing lows near 100, latest close sits on that support."""
    closes: list[float] = []
    # Several bounce cycles that bottom near 100.
    for _ in range(6):
        closes.extend([100.0, 101.5, 103.0, 105.0, 107.0, 105.5, 103.5, 102.0, 101.0, 100.2])
    # Drift up then settle back onto support.
    closes.extend([102.0, 104.0, 106.0, 104.0, 102.0, 100.5])

    day = date(2025, 1, 2)
    bars = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        low = close - 0.4
        # Emphasize trough bars as clear swing lows at 100.
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

    # Latest bar closes just above the ~100 support.
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
    # Crash well below the ~100 support.
    bars[-1]["close"] = 96.0
    bars[-1]["low"] = 95.5
    bars[-1]["high"] = 96.5
    matched, note = detect_close_at_support(bars)
    assert matched is False
    assert note is None


def test_evaluate_includes_close_at_support_flag():
    stock_bars, spy_bars = _paired()
    row = evaluate(
        {"symbol": "EXM", "name": "Example", "groups": ["sp500"], "sector": None, "industry": None},
        stock_bars,
        {"price": stock_bars[-1]["close"], "marketCap": 80e9, "quoteType": "EQUITY", "exchangeName": "NasdaqGS"},
        spy_bars,
    )
    assert "closeAtSupport" in row
    assert isinstance(row["closeAtSupport"], bool)
    assert "breakoutRetest" not in row
