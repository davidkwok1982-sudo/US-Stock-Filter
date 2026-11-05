"""Refresh the universe, cache Yahoo data, and serve stock detail."""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta, timezone

from app.config import CHUNK_SIZE, COOLDOWN_SECONDS, LIMIT, TTL_HOURS, WORKERS
from app.close_at_support import RULE_VERSION, detect_close_at_support
from app.evaluate import evaluate, spy_snapshot, summarize
from app.labels import industry_zh, sector_zh
from app.levels import find_levels, merge_flagged_support
from app.metrics import SCORE_RULE_VERSION, SMA_FAST, SMA_MID, SMA_SHORT, SMA_SLOW, SMA_ULTRA, breadth, rolling_sma
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
        self._industry_backfill_running = False

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
        self._set(progress=6, message=f"股票池 {total} 隻，正在下載 SPY")

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
                quote = quotes.get(item["symbol"])
                base = self._base_with_cached_profile(item, quote)
                rows.append(
                    evaluate(
                        base,
                        charts.get(item["symbol"]),
                        quote,
                        spy_bars,
                    )
                )

            # Persist progressive snapshot only when quotes landed; otherwise a
            # quote outage would overwrite a good cache with passHard=0 rows.
            if quotes:
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

        self._set(progress=91, message="正在補齊行業分類")
        # Cache for everyone; network fetch only passHard (5k Yahoo profile calls
        # stall refresh). Remaining labels backfill via /api/screen / background.
        self._enrich_rows_with_profiles(rows, fetch_missing=False, quiet=True)
        pass_hard = [row for row in rows if row.get("passHard")]
        self._enrich_rows_with_profiles(
            pass_hard,
            fetch_missing=True,
            pass_hard_first=True,
            quiet=False,
        )
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
        criteria = snapshot["meta"].setdefault("criteria", {})
        criteria["industrySource"] = "yahoo-assetProfile"
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

    def prepare_snapshot(self) -> dict | None:
        """Load snapshot and apply one-shot backfills. Returns None when cache is empty."""
        snapshot = store.load_snapshot()
        if snapshot is None:
            return None
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
            or any("rs20" not in row for row in snapshot["rows"])
            or any("beta" in row.get("failCodes", []) or "beta_missing" in row.get("failCodes", []) or "liquidity" in row.get("failCodes", []) for row in snapshot["rows"])
            or criteria.get("scoreRuleVersion") != SCORE_RULE_VERSION
        ):
            self._backfill_score_rules(snapshot)
        if self._needs_industry_backfill(snapshot):
            # FastAPI Cloud workers are short-lived; fill passHard synchronously so
            # the heatmap is correct on the same response, then backfill the rest.
            pass_hard = [row for row in snapshot["rows"] if row.get("passHard")]
            missing_pass = [row for row in pass_hard if self._row_needs_industry(row)]
            if missing_pass:
                self._enrich_rows_with_profiles(
                    missing_pass,
                    fetch_missing=True,
                    pass_hard_first=True,
                    quiet=True,
                )
                meta = snapshot.setdefault("meta", {})
                criteria = meta.setdefault("criteria", {})
                criteria["industrySource"] = "yahoo-assetProfile"
                store.save_snapshot(snapshot)
            if any(self._row_needs_industry(row) for row in snapshot["rows"]):
                self.start_industry_backfill()
        return snapshot

    def screen(self, include: str = "pass") -> dict:
        """Return screen payload. Default include=pass (passHard rows only); include=all for full universe."""
        refresh = self.status()
        snapshot = self.prepare_snapshot()
        if snapshot is None:
            return {"ready": False, "stale": False, "meta": None, "rows": [], "refresh": refresh}
        include_all = include == "all"
        slim = []
        for row in snapshot["rows"]:
            if not include_all and not row.get("passHard"):
                continue
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
            matched, note, flagged = detect_close_at_support(bars or [])
            row["closeAtSupport"] = matched
            row["closeAtSupportNote"] = note
            row["closeAtSupportLevel"] = round(flagged["price"], 2) if flagged else None
            row["closeAtSupportTouches"] = int(flagged["touches"]) if flagged else None
            row["closeAtSupportZoneLow"] = (
                round(flagged["zoneLow"], 2) if flagged and flagged.get("zoneLow") is not None else None
            )
            row["closeAtSupportZoneHigh"] = (
                round(flagged["zoneHigh"], 2) if flagged and flagged.get("zoneHigh") is not None else None
            )
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
            for key in ("closeAtSupport", "closeAtSupportNote", "closeAtSupportLevel", "closeAtSupportTouches", "closeAtSupportZoneLow", "closeAtSupportZoneHigh", "revenueGrowth", "earningsGrowth", "profitMargin"):
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
            # Weekly/hourly always hit Yahoo — fetch symbol + SPY in parallel.
            bars, spy = self._fetch_charts_parallel(client, symbol, interval)
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
        # Chart path is cache-only for fundamentals — never wait on Yahoo quoteSummary.
        # SPA loads /api/stock/{symbol}/profile when profilePending is true.
        fundamentals = self._fundamentals(symbol, allow_network=False)
        detail_row, profile = self._detail_row_and_profile(row, fundamentals)
        levels = find_levels(bars) if interval == "1d" else []
        if interval == "1d":
            matched, note, flagged = detect_close_at_support(bars)
            detail_row["closeAtSupport"] = matched
            detail_row["closeAtSupportNote"] = note
            detail_row["closeAtSupportLevel"] = (
                round(flagged["price"], 2) if flagged else None
            )
            detail_row["closeAtSupportTouches"] = (
                int(flagged["touches"]) if flagged else None
            )
            detail_row["closeAtSupportZoneLow"] = (
                round(flagged["zoneLow"], 2)
                if flagged and flagged.get("zoneLow") is not None
                else None
            )
            detail_row["closeAtSupportZoneHigh"] = (
                round(flagged["zoneHigh"], 2)
                if flagged and flagged.get("zoneHigh") is not None
                else None
            )
            if matched and flagged:
                levels = merge_flagged_support(levels, flagged)
        notes = build_notes(detail_row, levels)
        if fundamentals is None:
            profile_pending = True
        elif fundamentals.get("_summaryFetched") or "summary" in fundamentals:
            profile_pending = False
        else:
            # Light sector/industry cache from screen enrichment — upgrade async.
            profile_pending = True
        return {
            "row": detail_row,
            "interval": interval,
            "bars": [_public_bar(bar) for bar in bars],
            "sma10": _sma_points(bars, SMA_ULTRA),
            "sma20": _sma_points(bars, SMA_SHORT),
            "sma50": _sma_points(bars, SMA_FAST),
            "sma150": _sma_points(bars, SMA_MID),
            "sma200": _sma_points(bars, SMA_SLOW),
            "index": _index_series(spy, symbol="SPY", label="標普500（SPY）"),
            "levels": levels,
            "notes": notes,
            "profile": profile,
            "profilePending": profile_pending,
            "meta": None if snapshot is None else snapshot["meta"],
        }

    def profile(self, symbol: str) -> dict:
        """Secondary company profile fetch (may hit Yahoo). Does not block chart."""
        symbol = normalize_symbol(symbol)
        snapshot = store.load_snapshot()
        row = None
        if snapshot:
            row = next((item for item in snapshot["rows"] if item["symbol"] == symbol), None)
        fundamentals = self._fundamentals(
            symbol,
            allow_network=True,
            network_timeout=4.0,
            upgrade_summary=True,
        )
        if row is None:
            detail_row = {
                "symbol": symbol,
                "name": symbol,
                "sector": None,
                "industry": None,
                "pe": None,
            }
        else:
            detail_row = dict(row)
            detail_row.pop("beta", None)
            detail_row.pop("betaBasis", None)
        detail_row, profile = self._detail_row_and_profile(detail_row, fundamentals)
        notes = build_notes(detail_row, [])
        return {
            "row": {
                "symbol": detail_row.get("symbol"),
                "sector": detail_row.get("sector"),
                "industry": detail_row.get("industry"),
                "sectorEn": detail_row.get("sectorEn"),
                "industryEn": detail_row.get("industryEn"),
                "pe": detail_row.get("pe"),
                "revenueGrowth": detail_row.get("revenueGrowth"),
                "earningsGrowth": detail_row.get("earningsGrowth"),
                "profitMargin": detail_row.get("profitMargin"),
            },
            "profile": profile,
            "notes": {"fundamental": notes.get("fundamental") or []},
            "profilePending": False,
        }

    def _fetch_charts_parallel(self, client, symbol: str, interval: str) -> tuple[list, list]:
        bars: list = []
        spy: list = []

        def load_symbol() -> list:
            return client.chart(symbol, interval=interval) or []

        def load_spy() -> list:
            try:
                return client.chart("SPY", interval=interval) or []
            except Exception:
                log.exception("failed to load SPY %s chart for detail overlay", interval)
                return []

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_sym = pool.submit(load_symbol)
            fut_spy = pool.submit(load_spy)
            bars = fut_sym.result()
            spy = fut_spy.result()
        return bars, spy

    def _detail_row_and_profile(self, row: dict, fundamentals: dict | None) -> tuple[dict, dict | None]:
        detail_row = dict(row)
        detail_row.pop("beta", None)
        detail_row.pop("betaBasis", None)
        profile = None
        if not fundamentals:
            return detail_row, None
        if fundamentals.get("sector"):
            detail_row["sectorEn"] = fundamentals["sector"]
            detail_row["sector"] = sector_zh(fundamentals["sector"])
        if fundamentals.get("industry"):
            detail_row["industryEn"] = fundamentals["industry"]
            detail_row["industry"] = industry_zh(fundamentals["industry"])
        if "revenueGrowth" in fundamentals:
            detail_row["revenueGrowth"] = fundamentals.get("revenueGrowth")
        if "earningsGrowth" in fundamentals:
            detail_row["earningsGrowth"] = fundamentals.get("earningsGrowth")
        if "profitMargin" in fundamentals:
            detail_row["profitMargin"] = fundamentals.get("profitMargin")
        if fundamentals.get("pe") and not detail_row.get("pe"):
            detail_row["pe"] = fundamentals["pe"]
        sector_en = fundamentals.get("sector") or detail_row.get("sectorEn")
        industry_en = fundamentals.get("industry") or detail_row.get("industryEn")
        sector_label = detail_row.get("sector")
        industry_label = detail_row.get("industry")
        # Only expose a profile card when we have something useful beyond empty fields.
        has_card = any(
            [
                fundamentals.get("summary"),
                sector_label,
                industry_label,
                fundamentals.get("website"),
                fundamentals.get("employees"),
                fundamentals.get("hq"),
            ]
        )
        if has_card:
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
        return detail_row, profile

    def _base_with_cached_profile(self, item: dict, quote: dict | None) -> dict:
        """Merge universe row with quote/cache sector+industry before evaluate."""
        base = dict(item)
        quote = quote or {}
        sector = base.get("sector") or quote.get("sector")
        industry = base.get("industry") or quote.get("industry")
        if not sector or not industry:
            cached = self._cached_sector_industry(base["symbol"])
            if cached:
                sector = sector or cached.get("sector")
                industry = industry or cached.get("industry")
        base["sector"] = sector
        base["industry"] = industry
        return base

    def _cached_sector_industry(self, symbol: str) -> dict | None:
        cached = store.load_fundamentals(symbol)
        if not cached:
            return None
        sector = cached.get("sector")
        industry = cached.get("industry")
        if not sector and not industry:
            return None
        stamp = cached.get("updatedAt")
        if not stamp:
            return {"sector": sector, "industry": industry}
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError:
            return {"sector": sector, "industry": industry}
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - parsed > FUNDAMENTAL_TTL:
            return None
        return {"sector": sector, "industry": industry}

    def _apply_profile_to_row(self, row: dict, profile: dict | None) -> bool:
        if not profile:
            return False
        changed = False
        sector_en = profile.get("sector")
        industry_en = profile.get("industry")
        if sector_en and (not row.get("sectorEn") or not row.get("sector")):
            row["sectorEn"] = sector_en
            row["sector"] = sector_zh(sector_en)
            changed = True
        if industry_en and (not row.get("industryEn") or not row.get("industry")):
            row["industryEn"] = industry_en
            row["industry"] = industry_zh(industry_en)
            changed = True
        return changed

    def _persist_profile(self, symbol: str, profile: dict) -> None:
        existing = store.load_fundamentals(symbol) or {}
        existing.pop("updatedAt", None)
        if profile.get("sector"):
            existing["sector"] = profile["sector"]
        if profile.get("industry"):
            existing["industry"] = profile["industry"]
        store.save_fundamentals(symbol, existing)

    def _row_needs_industry(self, row: dict) -> bool:
        return not (
            row.get("industryEn")
            or row.get("sectorEn")
            or row.get("industry")
            or row.get("sector")
        )

    def _enrich_rows_with_profiles(
        self,
        rows: list[dict],
        *,
        fetch_missing: bool = True,
        pass_hard_first: bool = True,
        workers: int | None = None,
        quiet: bool = False,
    ) -> int:
        """Fill sector/industry from fundamentals cache and Yahoo assetProfile."""
        filled = 0
        missing: list[str] = []
        for row in rows:
            if not self._row_needs_industry(row):
                continue
            cached = self._cached_sector_industry(row["symbol"])
            if cached and self._apply_profile_to_row(row, cached):
                filled += 1
                continue
            if fetch_missing:
                missing.append(row["symbol"])

        if not fetch_missing or not missing:
            return filled

        if pass_hard_first:
            pass_hard = {row["symbol"] for row in rows if row.get("passHard")}
            missing.sort(key=lambda symbol: (0 if symbol in pass_hard else 1, symbol))

        worker_count = max(1, workers or WORKERS)
        client = get_client()
        total_missing = len(missing)
        chunk = max(50, CHUNK_SIZE)
        by_symbol = {row["symbol"]: row for row in rows}

        for start in range(0, total_missing, chunk):
            batch = missing[start : start + chunk]
            if not quiet:
                self._set(
                    progress=min(93, 91 + int(2 * start / max(total_missing, 1))),
                    message=f"正在補齊行業分類 {min(start + len(batch), total_missing)}/{total_missing}",
                )
            profiles = client.asset_profiles(batch, workers=worker_count)
            for symbol, profile in profiles.items():
                self._persist_profile(symbol, profile)
                row = by_symbol.get(symbol)
                if row and self._apply_profile_to_row(row, profile):
                    filled += 1
        log.info("industry enrich filled=%s fetched_attempt=%s", filled, total_missing)
        return filled

    def _needs_industry_backfill(self, snapshot: dict) -> bool:
        rows = snapshot.get("rows") or []
        targets = [row for row in rows if row.get("passHard")] or rows
        if not targets:
            return False
        return any(self._row_needs_industry(row) for row in targets)

    def start_industry_backfill(self) -> bool:
        with self._lock:
            if self._status["running"] or self._industry_backfill_running:
                return False
            self._industry_backfill_running = True
        threading.Thread(
            target=self._run_industry_backfill,
            name="kailut-industry-backfill",
            daemon=True,
        ).start()
        return True

    def _run_industry_backfill(self) -> None:
        try:
            snapshot = store.load_snapshot()
            if not snapshot:
                return
            rows = snapshot.get("rows") or []
            if not rows:
                return
            missing_pass = [
                row for row in rows if row.get("passHard") and self._row_needs_industry(row)
            ]
            log.info("industry backfill start missing_passHard=%s", len(missing_pass))
            # Fill passHard first and persist so the heatmap updates quickly.
            if missing_pass:
                filled_pass = self._enrich_rows_with_profiles(
                    missing_pass,
                    fetch_missing=True,
                    pass_hard_first=True,
                    quiet=True,
                )
                # Mirror labels onto the snapshot rows (same dict objects if shared).
                by_symbol = {row["symbol"]: row for row in rows}
                for row in missing_pass:
                    target = by_symbol.get(row["symbol"])
                    if target is not None and target is not row:
                        self._apply_profile_to_row(
                            target,
                            {
                                "sector": row.get("sectorEn") or row.get("sector"),
                                "industry": row.get("industryEn") or row.get("industry"),
                            },
                        )
                rows.sort(key=lambda row: (-row["score"], row["symbol"]))
                snapshot["rows"] = rows
                meta = snapshot.setdefault("meta", {})
                criteria = meta.setdefault("criteria", {})
                criteria["industrySource"] = "yahoo-assetProfile"
                store.save_snapshot(snapshot)
                log.info("industry backfill passHard filled=%s", filled_pass)
            # Then remaining evaluated rows from cache/Yahoo.
            filled_rest = self._enrich_rows_with_profiles(
                rows,
                fetch_missing=True,
                pass_hard_first=False,
                quiet=True,
            )
            rows.sort(key=lambda row: (-row["score"], row["symbol"]))
            snapshot["rows"] = rows
            meta = snapshot.setdefault("meta", {})
            criteria = meta.setdefault("criteria", {})
            criteria["industrySource"] = "yahoo-assetProfile"
            store.save_snapshot(snapshot)
            log.info("industry backfill done rest_filled=%s", filled_rest)
        except Exception:
            log.exception("industry backfill failed")
        finally:
            with self._lock:
                self._industry_backfill_running = False

    def _fundamentals_stamp(self, cached: dict | None) -> datetime | None:
        if not cached or not cached.get("updatedAt"):
            return None
        try:
            stamp = datetime.fromisoformat(cached["updatedAt"])
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp

    def _fundamentals(
        self,
        symbol: str,
        *,
        allow_network: bool = True,
        network_timeout: float = 1.5,
        upgrade_summary: bool = False,
    ) -> dict | None:
        """Load fundamentals with cache-first semantics.

        Previously a light sector/industry cache (no ``summary`` key) always
        forced a Yahoo quoteSummary round-trip. When Yahoo was slow/auth-flaky
        that stalled /api/stock for ~5s and blocked the chart.
        """
        cached = store.load_fundamentals(symbol)
        stamp = self._fundamentals_stamp(cached)
        fresh_enough = bool(stamp) and datetime.now(timezone.utc) - stamp < FUNDAMENTAL_TTL
        has_summary = bool(cached) and ("summary" in cached)
        if fresh_enough and cached is not None:
            if not upgrade_summary or has_summary:
                return cached
            # upgrade_summary: fall through to network even with a light cache.
        if not allow_network:
            return cached

        fresh = None
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(get_client().fundamentals, symbol)
                try:
                    fresh = fut.result(timeout=network_timeout)
                except FuturesTimeout:
                    log.warning(
                        "fundamentals timed out for %s after %.1fs",
                        symbol,
                        network_timeout,
                    )
                    fresh = None
        except Exception:
            log.exception("fundamentals failed for %s", symbol)
            fresh = None
        if fresh:
            # Mark that a full quoteSummary landed (summary key may still be null).
            fresh = dict(fresh)
            fresh["_summaryFetched"] = True
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
