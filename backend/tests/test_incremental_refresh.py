"""Incremental chart refresh and cold-boot behaviour."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from app.engine import chart_covers_session, engine, engine_hk, session_date_of
from app.main import _boot_market, hk_refresh, refresh, screen
from app.markets import HK_MARKET, US_MARKET
from app import screen_cache, store


def _isolate_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "market.sqlite")
    store._mem_snapshots["us"] = None
    store._mem_snapshots["hk"] = None


def _daily(end: date, *, open_: float, close: float, n: int = 4) -> list[dict]:
    start = end - timedelta(days=n - 1)
    bars = []
    for offset in range(n):
        day = start + timedelta(days=offset)
        bars.append(
            {
                "time": day.isoformat(),
                "open": open_,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
                "dollar": close * 1_000_000,
            }
        )
    return bars


class _FakeYahoo:
    def __init__(self, benchmark: str, benchmark_bars: list[dict], downloads: dict[str, list[dict]]):
        self.benchmark = benchmark
        self.benchmark_bars = benchmark_bars
        self.downloads = downloads
        self.chart_symbols: list[str] = []
        self.batch_calls: list[list[str]] = []
        self.quote_calls: list[list[str]] = []
        self.profile_calls: list[list[str]] = []

    def chart(self, symbol: str, interval: str = "1d") -> list[dict]:
        self.chart_symbols.append(symbol)
        assert symbol == self.benchmark
        assert interval == "1d"
        return self.benchmark_bars

    def charts(self, symbols: list[str], workers: int, on_each=None) -> dict[str, list[dict]]:
        self.batch_calls.append(list(symbols))
        found: dict[str, list[dict]] = {}
        for symbol in symbols:
            bars = self.downloads.get(symbol)
            if bars:
                found[symbol] = bars
            if on_each:
                on_each(symbol, bool(bars))
        return found

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        self.quote_calls.append(list(symbols))
        return {
            symbol: {
                "price": 50.0,
                "marketCap": 5_000_000_000,
                "quoteType": "EQUITY",
                "name": symbol,
                "changePct": 0.01,
            }
            for symbol in symbols
        }

    def asset_profiles(self, symbols: list[str], workers: int = 4) -> dict:
        self.profile_calls.append(list(symbols))
        return {}


def test_chart_covers_session_uses_last_bar_date():
    session = "2026-11-06"
    fresh = _daily(date(2026, 11, 6), open_=10, close=48)
    stale = _daily(date(2026, 11, 5), open_=10, close=48)
    assert chart_covers_session(fresh, session) is True
    assert chart_covers_session(stale, session) is False
    assert chart_covers_session(fresh, "2026-11-06T21:00:00") is True
    assert chart_covers_session([], session) is False
    assert chart_covers_session(fresh, None) is False
    assert chart_covers_session([{"time": 1_700_000_000, "close": 1}], session) is False
    assert session_date_of("2026-11-06") == "2026-11-06"
    assert session_date_of(1700000000) is None


@pytest.mark.parametrize(
    ("market_id", "names"),
    [
        ("us", ("KEEP", "OLD", "NEW", "MISS")),
        ("hk", ("0001.HK", "0002.HK", "0005.HK", "0011.HK")),
    ],
)
def test_refresh_reuses_charts_that_cover_the_benchmark_session(tmp_path, monkeypatch, market_id, names):
    """Fresh local bars skip Yahoo charts. Quotes still re-score every symbol."""
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.engine.LIMIT", None)
    keep, old, new, miss = names
    session = date(2026, 11, 6)
    market = US_MARKET if market_id == "us" else HK_MARKET
    eng = engine if market_id == "us" else engine_hk
    benchmark_bars = _daily(session, open_=400, close=410)
    keep_bars = _daily(session, open_=10, close=48)
    old_bars = _daily(session - timedelta(days=3), open_=20, close=40)
    old_fresh = _daily(session, open_=21, close=48)
    new_bars = _daily(session, open_=30, close=48)
    store.save_chart(keep, keep_bars, market=market_id)
    store.save_chart(old, old_bars, market=market_id)

    fake = _FakeYahoo(
        market.benchmark,
        benchmark_bars,
        {old: old_fresh, new: new_bars},
    )
    monkeypatch.setattr("app.engine.get_client", lambda: fake)
    constituents = [
        {"symbol": symbol, "name": symbol, "groups": [market_id], "sector": "Technology", "industry": "Software"}
        for symbol in names
    ]
    monkeypatch.setattr(eng, "_load_universe", lambda: (constituents, "test"))

    eng._refresh()

    assert fake.chart_symbols == [market.benchmark]
    assert fake.batch_calls == [[old, new, miss]]
    assert fake.quote_calls == [list(names)]
    assert fake.profile_calls == []

    assert store.load_chart(keep, market=market_id)[0]["open"] == 10
    assert store.load_chart(old, market=market_id)[0]["open"] == 21
    assert store.load_chart(old, market=market_id)[-1]["time"] == session.isoformat()
    assert store.load_chart(new, market=market_id)[0]["open"] == 30
    assert store.load_chart(miss, market=market_id) is None
    assert store.load_chart(market.benchmark, market=market_id)[-1]["time"] == session.isoformat()

    snapshot = store.load_snapshot(market_id)
    assert snapshot is not None
    meta = snapshot["meta"]
    assert meta["marketDate"] == session.isoformat()
    assert meta["market"] == market_id
    assert meta["chartReused"] == 1
    assert meta["chartFetched"] == 2
    assert meta["chartFailures"] == 1
    assert meta["universe"]["partial"] is False
    assert meta["universe"]["evaluated"] == 4
    by_symbol = {row["symbol"]: row for row in snapshot["rows"]}
    assert set(by_symbol) == set(names)
    # Quote price is inside 25% of the cached/fetched close, so Stage 2 uses it.
    for symbol in (keep, old, new):
        assert by_symbol[symbol]["price"] == 50
        assert by_symbol[symbol]["barsCount"] == 4
    assert by_symbol[miss]["barsCount"] == 0
    assert by_symbol[miss]["price"] == 50


def test_refresh_skips_chart_client_when_every_symbol_is_fresh(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr("app.engine.LIMIT", None)
    session = date(2026, 11, 6)
    bars = _daily(session, open_=10, close=48)
    store.save_chart("AAA", bars, market="us")
    store.save_chart("BBB", bars, market="us")
    fake = _FakeYahoo("SPY", _daily(session, open_=400, close=410), {})
    monkeypatch.setattr("app.engine.get_client", lambda: fake)
    constituents = [
        {"symbol": symbol, "name": symbol, "groups": ["us"], "sector": "Technology", "industry": "Software"}
        for symbol in ("AAA", "BBB")
    ]
    monkeypatch.setattr(engine, "_load_universe", lambda: (constituents, "test"))

    engine._refresh()

    assert fake.batch_calls == []
    assert fake.quote_calls == [["AAA", "BBB"]]
    snapshot = store.load_snapshot("us")
    assert snapshot["meta"]["chartReused"] == 2
    assert snapshot["meta"]["chartFetched"] == 0
    assert snapshot["meta"]["chartFailures"] == 0
    assert {row["symbol"] for row in snapshot["rows"]} == {"AAA", "BBB"}


def test_boot_does_not_auto_refresh_empty_or_stale_cache(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    started: list[str] = []
    monkeypatch.setattr(engine, "start", lambda: started.append("us") or True)
    monkeypatch.setattr(engine_hk, "start", lambda: started.append("hk") or True)
    monkeypatch.setattr(engine, "start_industry_backfill", lambda: started.append("us-ind") or True)
    monkeypatch.setattr(engine_hk, "start_industry_backfill", lambda: started.append("hk-ind") or True)

    _boot_market("us")
    _boot_market("hk")
    assert started == []

    stale = {
        "meta": {"refreshedAt": "2020-01-01T00:00:00+00:00"},
        "rows": [{"symbol": "AAA", "passHard": True, "score": 1, "industry": None, "sector": None}],
    }
    store.save_snapshot(stale, market="us")
    store.save_snapshot(stale, market="hk")
    _boot_market("us")
    _boot_market("hk")
    assert started == []


def test_boot_still_backfills_industry_when_cache_is_fresh(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(engine, "start", lambda: calls.append("refresh") or True)
    monkeypatch.setattr(engine, "start_industry_backfill", lambda: calls.append("industry") or True)
    monkeypatch.setattr(store, "is_stale", lambda snapshot, ttl_hours=12: False)
    store.save_snapshot(
        {
            "meta": {"refreshedAt": datetime.now(timezone.utc).isoformat(), "criteria": {}},
            "rows": [
                {
                    "symbol": "NEEDY",
                    "passHard": True,
                    "score": 80,
                    "industry": None,
                    "industryEn": None,
                    "sector": None,
                    "sectorEn": None,
                }
            ],
        },
        market="us",
    )
    _boot_market("us")
    assert calls == ["industry"]


def test_manual_refresh_still_starts_and_markets_stay_exclusive(monkeypatch):
    idle = {"running": False, "progress": 0, "message": "尚未更新", "error": None}
    busy = {"running": True, "progress": 40, "message": "正在下載日線", "error": None}
    monkeypatch.setattr("app.main.cooldown_block", lambda force=False, market="us": None)
    us_started: list[bool] = []
    hk_started: list[bool] = []
    monkeypatch.setattr(engine, "start", lambda: us_started.append(True) or True)
    monkeypatch.setattr(engine_hk, "start", lambda: hk_started.append(True) or True)
    monkeypatch.setattr(engine, "status", lambda: dict(idle))
    monkeypatch.setattr(engine_hk, "status", lambda: dict(idle))

    us = refresh(force=False)
    hk = hk_refresh(force=False)
    assert us["started"] is True
    assert hk["started"] is True
    assert us_started == [True]
    assert hk_started == [True]

    monkeypatch.setattr(engine_hk, "status", lambda: dict(busy))
    blocked = refresh(force=True)
    assert blocked["started"] is False
    assert blocked["reason"] == "busy"
    assert us_started == [True]

    monkeypatch.setattr(engine_hk, "status", lambda: dict(idle))
    monkeypatch.setattr(engine, "status", lambda: dict(busy))
    blocked_hk = hk_refresh(force=True)
    assert blocked_hk["started"] is False
    assert blocked_hk["reason"] == "busy"
    assert hk_started == [True]


def test_us_empty_screen_prompts_manual_refresh(monkeypatch):
    screen_cache.invalidate("us")
    idle = {"running": False, "progress": 0, "message": "尚未更新", "error": None}
    monkeypatch.setattr(engine, "status", lambda: dict(idle))
    monkeypatch.setattr(engine, "prepare_snapshot", lambda: None)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/screen",
        "raw_path": b"/api/screen",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    body = screen(Request(scope))
    assert body["ready"] is False
    assert body["rows"] == []
    assert body["refresh"]["running"] is False
    assert "重新整理" in body["meta"]["hint"]
