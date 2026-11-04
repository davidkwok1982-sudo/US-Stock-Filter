"""Refresh the universe, cache Yahoo data, and serve stock detail."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from app.config import COOLDOWN_SECONDS, LIMIT, TTL_HOURS, WORKERS
from app.close_at_support import RULE_VERSION, detect_close_at_support
from app.evaluate import evaluate, spy_snapshot, summarize
from app.labels import industry_zh, sector_zh
from app.levels import find_levels
from app.metrics import SMA_FAST, SMA_SLOW, breadth, rolling_sma
from app.notes import build_notes
from app import store
from app.universe import load_universe
from app.yahoo import get_client, normalize_interval

log = logging.getLogger("kailut")

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9\-]{0,9}$")
FUNDAMENTAL_TTL = timedelta(days=7)


class Engine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = {
            "running": False,
            "progress": 0,
            "message": "尚未更新",
            "error": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _set(self, **kwargs) -> None:
        with self._lock:
            self._status.update(kwargs)

    def start(self) -> bool:
        with self._lock:
            if self._status["running"]:
                return False
            self._status = {
                "running": True,
                "progress": 1,
                "message": "開始更新",
                "error": None,
            }
            threading.Thread(target=self._run, name="kailut-refresh", daemon=True).start()
            return True

    def _run(self) -> None:
        try:
            self._refresh()
            self._set(running=False, progress=100, message="更新完成", error=None)
        except RuntimeError as exc:
            log.warning("refresh rejected: %s", exc)
            self._set(running=False, message="更新失敗", error=str(exc))
        except Exception:
            log.exception("refresh failed")
            self._set(running=False, message="更新失敗", error="更新時發生問題，請稍後再試")

    def _refresh(self) -> None:
        self._set(progress=3, message="正在讀取指數成份")
        constituents, source = load_universe()
        if LIMIT:
            constituents = constituents[:LIMIT]
        symbols = [item["symbol"] for item in constituents]
        self._set(progress=8, message=f"成份 {len(symbols)} 隻，正在下載日線")

        client = get_client()
        targets = symbols + ["SPY"]
        counter = {"n": 0}
        counter_lock = threading.Lock()
        total = len(targets)

        def on_each(_symbol: str, _ok: bool) -> None:
            with counter_lock:
                counter["n"] += 1
                done = counter["n"]
            if done == total or done % 20 == 0:
                progress = 8 + int(70 * done / total)
                self._set(progress=progress, message=f"正在下載日線 {done}/{total}")

        charts = client.charts(targets, workers=WORKERS, on_each=on_each)
        if "SPY" not in charts:
            raise RuntimeError("未能下載 SPY，貝他無法計算，未覆寫快取")
        ok = sum(1 for symbol in symbols if symbol in charts)
        if ok < 0.7 * len(symbols):
            raise RuntimeError(f"日線下載不完整（{ok}/{len(symbols)}），未覆寫快取")

        self._set(progress=80, message="正在讀取市值與報價")
        quotes = client.quotes(symbols)
        if len(quotes) < 0.6 * len(symbols):
            raise RuntimeError(f"報價下載不足（{len(quotes)}/{len(symbols)}），未覆寫快取")

        self._set(progress=86, message="正在讀取貝他")
        vendor_betas = client.betas(symbols, workers=min(8, WORKERS))

        self._set(progress=92, message="正在計算均線、貝他與評分")
        spy_bars = charts["SPY"]
        rows = [
            evaluate(
                item,
                charts.get(item["symbol"]),
                quotes.get(item["symbol"]),
                spy_bars,
                vendor_beta=vendor_betas.get(item["symbol"]),
            )
            for item in constituents
        ]
        rows.sort(key=lambda row: (-row["score"], row["symbol"]))
        summary = summarize(rows)
        counts = {"sp500": 0, "ndx": 0, "sp400": 0, "unique": len(constituents)}
        for item in constituents:
            for group in item["groups"]:
                counts[group] = counts.get(group, 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "meta": {
                "refreshedAt": now,
                "marketDate": spy_bars[-1]["time"],
                "universeSource": source,
                "universe": counts,
                "summary": summary,
                "breadth": breadth(summary["pass"]),
                "spy": spy_snapshot(spy_bars),
                "source": "Yahoo Finance 圖表與報價（免費公開接口，無需 API 金鑰）",
                "betaMethod": "優先用 Yahoo Finance 公布的貝他。若該欄為空，改以過去約90個重疊交易日的日回報對 SPY 估算，並在表內標明。少於60個觀測則列為未明。",
                "dollarVolumeMethod": "優先取過去63個交易日的未還原收市價乘成交量之平均；不足則用三個月平均成交量乘現價。門檻為3,000萬美元。",
                "adjustment": "K線及均線使用拆股還原價；成交額用未還原收市價乘成交量。",
                "ttlHours": TTL_HOURS,
                "chartFailures": len(symbols) - ok,
                "criteria": {
                    "minMarketCap": 2_000_000_000,
                    "minDollarVolume": 30_000_000,
                    "minBeta": 1,
                    "nearHighWithin": 0.25,
                    "closeAtSupportRuleVersion": RULE_VERSION,
                    "breadthBullish": 200,
                    "breadthCautiousBelow": 100,
                },
            },
            "rows": rows,
        }
        self._set(progress=96, message="正在寫入本機快取")
        store.save_refresh(snapshot, charts)
        log.info(
            "refresh done universe=%s pass=%s failures=%s",
            len(rows),
            summary["pass"],
            len(symbols) - ok,
        )

    def screen(self) -> dict:
        snapshot = store.load_snapshot()
        refresh = self.status()
        if snapshot is None:
            return {"ready": False, "stale": False, "meta": None, "rows": [], "refresh": refresh}
        meta = snapshot.get("meta") or {}
        criteria = meta.get("criteria") or {}
        if (
            any("closeAtSupport" not in row for row in snapshot["rows"])
            or criteria.get("closeAtSupportRuleVersion") != RULE_VERSION
        ):
            self._backfill_close_at_support(snapshot)
        slim = []
        for row in snapshot["rows"]:
            item = dict(row)
            item.pop("scoreParts", None)
            slim.append(item)
        return {
            "ready": True,
            "stale": store.is_stale(snapshot),
            "meta": snapshot["meta"],
            "rows": slim,
            "refresh": refresh,
        }

    def _backfill_close_at_support(self, snapshot: dict) -> None:
        """Fill closeAtSupport on older cached rows from daily charts (one-shot)."""
        for row in snapshot["rows"]:
            bars = store.load_chart(row["symbol"])
            matched, note = detect_close_at_support(bars or [])
            row["closeAtSupport"] = matched
            row["closeAtSupportNote"] = note
            row.pop("breakoutRetest", None)
            row.pop("breakoutRetestNote", None)
        meta = snapshot.setdefault("meta", {})
        criteria = meta.setdefault("criteria", {})
        criteria["closeAtSupportRuleVersion"] = RULE_VERSION
        criteria.pop("breakoutRetestRuleVersion", None)
        store.save_snapshot(snapshot)
        log.info("backfilled closeAtSupport v%s on %s cached rows", RULE_VERSION, len(snapshot["rows"]))

    def detail(self, symbol: str, interval: str = "1d") -> dict:
        symbol = normalize_symbol(symbol)
        interval = normalize_interval(interval)
        snapshot = store.load_snapshot()
        row = None
        if snapshot:
            row = next((item for item in snapshot["rows"] if item["symbol"] == symbol), None)
        client = get_client()
        quote = None
        # Daily bars stay on the refresh SQLite cache; weekly/hourly are fetched live so
        # the screen cache is not mixed with other granularities.
        if interval == "1d":
            bars = store.load_chart(symbol)
            if bars is None or row is None:
                quote_map = client.quotes([symbol])
                quote = quote_map.get(symbol)
                if quote and quote.get("quoteType") not in (None, "EQUITY"):
                    raise LookupError("這不是美股普通股")
            if bars is None:
                bars = client.chart(symbol, interval="1d")
                if bars:
                    store.save_chart(symbol, bars)
            spy = store.load_chart("SPY") or []
            if not spy:
                try:
                    spy = client.chart("SPY", interval="1d") or []
                    if spy:
                        store.save_chart("SPY", spy)
                except Exception:
                    log.exception("failed to load SPY chart for detail overlay")
                    spy = []
        else:
            if row is None:
                quote_map = client.quotes([symbol])
                quote = quote_map.get(symbol)
                if quote and quote.get("quoteType") not in (None, "EQUITY"):
                    raise LookupError("這不是美股普通股")
            bars = client.chart(symbol, interval=interval) or []
            try:
                spy = client.chart("SPY", interval=interval) or []
            except Exception:
                log.exception("failed to load SPY %s chart for detail overlay", interval)
                spy = []
        if not bars:
            raise LookupError("找不到這隻股份的圖表資料")
        # Evaluate / score always use daily bars when available so Stage 2 maths stay consistent.
        eval_bars = bars
        eval_spy = spy
        if interval != "1d":
            daily = store.load_chart(symbol)
            daily_spy = store.load_chart("SPY") or []
            if daily:
                eval_bars = daily
            if daily_spy:
                eval_spy = daily_spy
        if row is None:
            if quote is None:
                quote = client.quotes([symbol]).get(symbol) or {}
            base = {
                "symbol": symbol,
                "name": (quote or {}).get("name") or symbol,
                "groups": [],
                "sector": None,
                "industry": None,
            }
            row = evaluate(
                base,
                eval_bars,
                quote or {},
                eval_spy,
                vendor_beta=client.vendor_beta(symbol),
            )
        fundamentals = self._fundamentals(symbol)
        detail_row = dict(row)
        if fundamentals:
            if fundamentals.get("sector"):
                detail_row["sectorEn"] = fundamentals["sector"]
                detail_row["sector"] = sector_zh(fundamentals["sector"])
            if fundamentals.get("industry"):
                detail_row["industryEn"] = fundamentals["industry"]
                detail_row["industry"] = industry_zh(fundamentals["industry"])
            detail_row["revenueGrowth"] = fundamentals.get("revenueGrowth")
            detail_row["earningsGrowth"] = fundamentals.get("earningsGrowth")
            detail_row["profitMargin"] = fundamentals.get("profitMargin")
            if fundamentals.get("pe") and not detail_row.get("pe"):
                detail_row["pe"] = fundamentals["pe"]
        # Support/resistance from the displayed series; SMA50/200 are bar windows on that series
        # (days / weeks / hours), matching the current daily behaviour.
        levels = find_levels(bars) if interval == "1d" else []
        notes = build_notes(detail_row, levels)
        return {
            "row": detail_row,
            "interval": interval,
            "bars": [_public_bar(bar) for bar in bars],
            "sma50": _sma_points(bars, SMA_FAST),
            "sma200": _sma_points(bars, SMA_SLOW),
            "index": _index_series(spy, symbol="SPY", label="標普500（SPY）"),
            "levels": levels,
            "notes": notes,
            "meta": None if snapshot is None else snapshot["meta"],
        }

    def _fundamentals(self, symbol: str) -> dict | None:
        cached = store.load_fundamentals(symbol)
        if cached and cached.get("updatedAt"):
            stamp = datetime.fromisoformat(cached["updatedAt"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - stamp < FUNDAMENTAL_TTL:
                return cached
        try:
            fresh = get_client().fundamentals(symbol)
        except Exception:
            log.exception("fundamentals failed for %s", symbol)
            fresh = None
        if fresh:
            store.save_fundamentals(symbol, fresh)
            return fresh
        return cached


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace(".", "-")
    if not SYMBOL_RE.fullmatch(cleaned):
        raise ValueError("代號格式不正確")
    return cleaned



def _index_series(bars: list[dict], *, symbol: str, label: str) -> dict:
    """Benchmark OHLC + closes for the stock chart index pane; empty when missing."""
    closes = []
    public = []
    for bar in bars:
        closes.append({"time": bar["time"], "value": round(bar["close"], 4 if bar["close"] < 1 else 2)})
        public.append(_public_bar(bar))
    return {"symbol": symbol, "label": label, "closes": closes, "bars": public}


def _public_bar(bar: dict) -> dict:
    time = bar["time"]
    return {
        "time": int(time) if isinstance(time, (int, float)) else time,
        "open": round(bar["open"], 4 if bar["open"] < 1 else 2),
        "high": round(bar["high"], 4 if bar["high"] < 1 else 2),
        "low": round(bar["low"], 4 if bar["low"] < 1 else 2),
        "close": round(bar["close"], 4 if bar["close"] < 1 else 2),
        "volume": int(bar["volume"]),
    }


def _sma_points(bars: list[dict], window: int) -> list[dict]:
    series = rolling_sma([bar["close"] for bar in bars], window)
    points = []
    for bar, value in zip(bars, series):
        if value is None:
            continue
        points.append({"time": bar["time"], "value": round(value, 4 if value < 1 else 2)})
    return points


def cooldown_block(force: bool) -> str | None:
    if force:
        return None
    snapshot = store.load_snapshot()
    if snapshot is None:
        return None
    age = store.age_seconds(snapshot)
    if age is not None and age < COOLDOWN_SECONDS:
        return "剛剛更新過，請五分鐘後再試"
    return None


engine = Engine()
