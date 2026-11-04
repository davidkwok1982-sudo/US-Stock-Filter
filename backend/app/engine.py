"""Refresh the universe, cache Yahoo data, and serve stock detail."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from app.config import CHUNK_SIZE, COOLDOWN_SECONDS, LIMIT, TTL_HOURS, WORKERS
from app.close_at_support import RULE_VERSION, detect_close_at_support
from app.evaluate import evaluate, spy_snapshot, summarize
from app.labels import industry_zh, sector_zh
from app.levels import find_levels
from app.metrics import SCORE_RULE_VERSION, SMA_FAST, SMA_MID, SMA_SLOW, breadth, rolling_sma
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
        self._set(progress=3, message="正在讀取美股符號目錄")
        constituents, source = load_universe()
        if LIMIT:
            constituents = constituents[:LIMIT]
        symbols = [item["symbol"] for item in constituents]
        total = len(symbols)
        self._set(progress=6, message=f"宇宙 {total} 隻，正在下載 SPY")

        client = get_client()
        spy_bars = client.chart("SPY")
        if not spy_bars:
            raise RuntimeError("未能下載 SPY，相對強度無法計算，未覆寫快取")
        store.save_chart("SPY", spy_bars)

        rows: list[dict] = []
        chart_ok = 0
        quote_ok = 0
        chunk = max(50, CHUNK_SIZE)
        batches = (total + chunk - 1) // chunk if total else 1

        for batch_index in range(0, total, chunk):
            batch = constituents[batch_index : batch_index + chunk]
            batch_symbols = [item["symbol"] for item in batch]
            done_before = batch_index
            batch_no = batch_index // chunk + 1
            self._set(
                progress=min(88, 8 + int(80 * done_before / max(total, 1))),
                message=f"分批下載日線 {done_before}/{total}（第 {batch_no}/{batches} 批）",
            )

            counter = {"n": 0}
            counter_lock = threading.Lock()

            def on_each(_symbol: str, _ok: bool) -> None:
                with counter_lock:
                    counter["n"] += 1
                    local_done = counter["n"]
                absolute = done_before + local_done
                if local_done == len(batch_symbols) or local_done % 25 == 0:
                    progress = 8 + int(80 * absolute / max(total, 1))
                    self._set(
                        progress=min(88, progress),
                        message=f"正在下載日線 {absolute}/{total}",
                    )

            charts = client.charts(batch_symbols, workers=WORKERS, on_each=on_each)
            chart_ok += sum(1 for symbol in batch_symbols if symbol in charts)
            store.upsert_charts(charts)

            self._set(
                progress=min(90, 8 + int(80 * (done_before + len(batch_symbols)) / max(total, 1))),
                message=f"正在讀取報價 {done_before + len(batch_symbols)}/{total}",
            )
            quotes = client.quotes(batch_symbols)
            quote_ok += len(quotes)

            for item in batch:
                rows.append(
                    evaluate(
                        item,
                        charts.get(item["symbol"]),
                        quotes.get(item["symbol"]),
                        spy_bars,
                    )
                )

            # Persist progressive snapshot so the UI can show a growing screen.
            rows.sort(key=lambda row: (-row["score"], row["symbol"]))
            snapshot = self._build_snapshot(
                rows=rows,
                spy_bars=spy_bars,
                source=source,
                universe_size=total,
                chart_failures=len(symbols) - chart_ok,
                partial=batch_index + len(batch) < total,
            )
            store.save_snapshot(snapshot)
            # Free batch charts from memory.
            del charts

        if chart_ok < 0.4 * total:
            raise RuntimeError(f"日線下載不完整（{chart_ok}/{total}），未覆寫快取")
        if quote_ok < 0.3 * total:
            raise RuntimeError(f"報價下載不足（{quote_ok}/{total}），未覆寫快取")

        self._set(progress=94, message="正在整理結果")
        rows.sort(key=lambda row: (-row["score"], row["symbol"]))
        snapshot = self._build_snapshot(
            rows=rows,
            spy_bars=spy_bars,
            source=source,
            universe_size=total,
            chart_failures=len(symbols) - chart_ok,
            partial=False,
        )
        store.save_snapshot(snapshot)
        store.prune_charts(set(symbols) | {"SPY"})
        summary = snapshot["meta"]["summary"]
        log.info(
            "refresh done universe=%s pass=%s failures=%s",
            len(rows),
            summary["pass"],
            len(symbols) - chart_ok,
        )

    def _build_snapshot(
        self,
        *,
        rows: list[dict],
        spy_bars: list[dict],
        source: str,
        universe_size: int,
        chart_failures: int,
        partial: bool,
    ) -> dict:
        summary = summarize(rows)
        now = datetime.now(timezone.utc).isoformat()
        return {
            "meta": {
                "refreshedAt": now,
                "marketDate": spy_bars[-1]["time"],
                "universeSource": source,
                "universe": {
                    "unique": universe_size,
                    "evaluated": len(rows),
                    "partial": partial,
                },
                "summary": summary,
                "breadth": breadth(summary["pass"]),
                "spy": spy_snapshot(spy_bars),
                "source": "Yahoo Finance 圖表與報價（免費公開接口，無需 API 金鑰）",
                "dollarVolumeMethod": "優先取過去63個交易日的未還原收市價乘成交量之平均；不足則用三個月平均成交量乘現價。流動性只作評分，不作硬性門檻。",
                "adjustment": "K線及均線使用拆股還原價；成交額用未還原收市價乘成交量。",
                "ttlHours": TTL_HOURS,
                "chartFailures": chart_failures,
                "criteria": {
                    "minMarketCap": 2_000_000_000,
                    "nearHighWithin": 0.25,
                    "closeAtSupportRuleVersion": RULE_VERSION,
                    "scoreRuleVersion": SCORE_RULE_VERSION,
                    "breadthBullish": 200,
                    "breadthCautiousBelow": 100,
                },
            },
            "rows": rows,
        }

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
        criteria = (snapshot.get("meta") or {}).get("criteria") or {}
        if (
            any("rs1w" not in row for row in snapshot["rows"])
            or any("beta" in row.get("failCodes", []) or "beta_missing" in row.get("failCodes", []) or "liquidity" in row.get("failCodes", []) for row in snapshot["rows"])
            or criteria.get("scoreRuleVersion") != SCORE_RULE_VERSION
        ):
            self._backfill_score_rules(snapshot)
        slim = []
        for row in snapshot["rows"]:
            item = dict(row)
            item.pop("scoreParts", None)
            item.pop("beta", None)
            item.pop("betaBasis", None)
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

    def _backfill_score_rules(self, snapshot: dict) -> None:
        """Recompute Stage 2 rows (hard gates, score, RS) when score rules change."""
        spy_bars = store.load_chart("SPY") or []
        updated = []
        for row in snapshot["rows"]:
            bars = store.load_chart(row["symbol"])
            quote = {
                "price": row.get("price"),
                "changePct": row.get("changePct"),
                "marketCap": row.get("marketCap"),
                "pe": row.get("pe"),
                "name": row.get("name"),
                "exchange": row.get("exchange"),
                "exchangeName": row.get("exchange"),
                "quoteType": "EQUITY",
                "avgVolume3m": None,
            }
            base = {
                "symbol": row["symbol"],
                "name": row.get("name") or row["symbol"],
                "groups": list(row.get("groups") or []),
                "sector": row.get("sectorEn") or row.get("sector"),
                "industry": row.get("industryEn") or row.get("industry"),
            }
            fresh = evaluate(base, bars, quote, spy_bars)
            for key in ("closeAtSupport", "closeAtSupportNote", "revenueGrowth", "earningsGrowth", "profitMargin"):
                if key in row:
                    fresh[key] = row[key]
            updated.append(fresh)
        updated.sort(key=lambda item: (-item["score"], item["symbol"]))
        snapshot["rows"] = updated
        meta = snapshot.setdefault("meta", {})
        if spy_bars:
            meta["spy"] = spy_snapshot(spy_bars)
            meta["summary"] = summarize(updated)
            meta["breadth"] = breadth(meta["summary"]["pass"])
        criteria = meta.setdefault("criteria", {})
        criteria["scoreRuleVersion"] = SCORE_RULE_VERSION
        criteria.pop("minBeta", None)
        criteria.pop("minDollarVolume", None)
        # Normalize universe meta shape for older snapshots.
        universe = meta.get("universe")
        if isinstance(universe, dict) and "unique" in universe and "evaluated" not in universe:
            universe["evaluated"] = len(updated)
            universe.setdefault("partial", False)
        store.save_snapshot(snapshot)
        log.info("backfilled score rules v%s on %s cached rows", SCORE_RULE_VERSION, len(updated))

    def detail(self, symbol: str, interval: str = "1d") -> dict:
        symbol = normalize_symbol(symbol)
        interval = normalize_interval(interval)
        snapshot = store.load_snapshot()
        row = None
        if snapshot:
            row = next((item for item in snapshot["rows"] if item["symbol"] == symbol), None)
        client = get_client()
        quote = None
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
            row = evaluate(base, eval_bars, quote or {}, eval_spy)
        fundamentals = self._fundamentals(symbol)
        detail_row = dict(row)
        detail_row.pop("beta", None)
        detail_row.pop("betaBasis", None)
        profile = None
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
            sector_en = fundamentals.get("sector") or detail_row.get("sectorEn")
            industry_en = fundamentals.get("industry") or detail_row.get("industryEn")
            sector_label = detail_row.get("sector")
            industry_label = detail_row.get("industry")
            profile = {
                "summary": fundamentals.get("summary"),
                "sector": sector_label,
                "industry": industry_label,
                "sectorZh": sector_label,
                "industryZh": industry_label,
                "sectorEn": sector_en,
                "industryEn": industry_en,
                "website": fundamentals.get("website"),
                "employees": fundamentals.get("employees"),
                "hq": fundamentals.get("hq"),
                "city": fundamentals.get("city"),
                "state": fundamentals.get("state"),
                "country": fundamentals.get("country"),
                "phone": fundamentals.get("phone"),
                "source": "Yahoo Finance public quoteSummary (assetProfile)",
            }
        levels = find_levels(bars) if interval == "1d" else []
        notes = build_notes(detail_row, levels)
        return {
            "row": detail_row,
            "interval": interval,
            "bars": [_public_bar(bar) for bar in bars],
            "sma50": _sma_points(bars, SMA_FAST),
            "sma150": _sma_points(bars, SMA_MID),
            "sma200": _sma_points(bars, SMA_SLOW),
            "index": _index_series(spy, symbol="SPY", label="標普500（SPY）"),
            "levels": levels,
            "notes": notes,
            "profile": profile,
            "meta": None if snapshot is None else snapshot["meta"],
        }

    def _fundamentals(self, symbol: str) -> dict | None:
        cached = store.load_fundamentals(symbol)
        cache_has_profile = bool(cached) and "summary" in cached
        if cached and cache_has_profile and cached.get("updatedAt"):
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
