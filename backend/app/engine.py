"""Refresh the universe, cache Yahoo data, and serve stock detail."""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta, timezone

from app.config import CHUNK_SIZE, COOLDOWN_SECONDS, LIMIT, TTL_HOURS, WORKERS
from app.close_at_support import RULE_VERSION, detect_close_at_resistance, detect_close_at_support
from app.evaluate import apply_close_at_resistance, evaluate, normalize_side, spy_snapshot, summarize
from app.labels import industry_zh, sector_zh
from app.levels import find_levels, merge_flagged_resistance, merge_flagged_support
from app.markets import HK_MARKET, US_MARKET, MarketConfig
from app.metrics import (
    SCORE_RULE_VERSION,
    SHORT_RULE_VERSION,
    SMA_FAST,
    SMA_MID,
    SMA_SHORT,
    SMA_SLOW,
    SMA_ULTRA,
    rolling_sma,
)
from app.notes import build_notes
from app import store
from app.universe import load_universe as load_universe_us
from app.universe_hk import load_universe as load_universe_hk
from app.yahoo import get_client, normalize_interval

log = logging.getLogger("kailut")

US_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9\-]{0,9}$")
HK_SYMBOL_RE = re.compile(r"^\d{4}\.HK$")
SYMBOL_RE = US_SYMBOL_RE  # backward-compatible alias
FUNDAMENTAL_TTL = timedelta(days=7)


class Engine:
    def __init__(self, market: MarketConfig | None = None) -> None:
        self.market = market or US_MARKET
        self._lock = threading.Lock()
        self._status = {
            "running": False,
            "progress": 0,
            "message": "尚未更新",
            "error": None,
        }
        self._industry_backfill_running = False

    @property
    def mid(self) -> str:
        return self.market.id

    def _load_universe(self):
        if self.mid == "hk":
            return load_universe_hk()
        return load_universe_us()

    def _eval_kwargs(self) -> dict:
        return {
            "min_market_cap": self.market.min_market_cap,
            "micro_cap": self.market.micro_cap,
            "penny_price": self.market.penny_price,
            "apply_otc_gate": self.market.apply_otc_gate,
            "cap_fail_label": self.market.cap_fail_label,
            "rs_label": self.market.rs_score_label,
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
            threading.Thread(target=self._run, name=f"kailut-refresh-{self.mid}", daemon=True).start()
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
        pool_label = "港股證券名單" if self.mid == "hk" else "美股符號目錄"
        bench = self.market.benchmark
        self._set(progress=3, message=f"正在讀取{pool_label}")
        constituents, source = self._load_universe()
        if LIMIT:
            constituents = constituents[:LIMIT]
        symbols = [item["symbol"] for item in constituents]
        total = len(symbols)
        self._set(progress=6, message=f"股票池 {total} 隻，正在下載 {bench}")

        client = get_client()
        spy_bars = client.chart(bench)
        if not spy_bars:
            raise RuntimeError(f"未能下載 {bench}，相對強度無法計算，未覆寫快取")
        store.save_chart(bench, spy_bars, market=self.mid)

        rows: list[dict] = []
        short_rows: list[dict] = []
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
            store.upsert_charts(charts, market=self.mid)

            self._set(
                progress=min(90, 8 + int(80 * (done_before + len(batch_symbols)) / max(total, 1))),
                message=f"正在讀取報價 {done_before + len(batch_symbols)}/{total}",
            )
            quotes = client.quotes(batch_symbols)
            quote_ok += len(quotes)

            for item in batch:
                quote = quotes.get(item["symbol"])
                base = self._base_with_cached_profile(item, quote)
                bars = charts.get(item["symbol"])
                kwargs = self._eval_kwargs()
                rows.append(
                    evaluate(
                        base,
                        bars,
                        quote,
                        spy_bars,
                        side="long",
                        **kwargs,
                    )
                )
                short_row = evaluate(
                    base,
                    bars,
                    quote,
                    spy_bars,
                    side="short",
                    detect_levels=False,
                    **kwargs,
                )
                if short_row["passHard"]:
                    apply_close_at_resistance(short_row, bars)
                short_rows.append(short_row)

            # Persist progressive snapshot only when quotes landed; otherwise a
            # quote outage would overwrite a good cache with passHard=0 rows.
            if quotes:
                self._sync_short_labels(rows, short_rows)
                rows.sort(key=lambda row: (-row["score"], row["symbol"]))
                short_rows.sort(key=lambda row: (-row["score"], row["symbol"]))
                snapshot = self._build_snapshot(
                    rows=rows,
                    rows_short=short_rows,
                    spy_bars=spy_bars,
                    source=source,
                    universe_size=total,
                    chart_failures=len(symbols) - chart_ok,
                    partial=batch_index + len(batch) < total,
                )
                store.save_snapshot(snapshot, market=self.mid)
            # Free batch charts from memory.
            del charts

        if chart_ok < 0.4 * total:
            raise RuntimeError(f"日線下載不完整（{chart_ok}/{total}），未覆寫快取")
        if quote_ok < 0.3 * total:
            raise RuntimeError(f"報價下載不足（{quote_ok}/{total}），未覆寫快取")

        self._set(progress=91, message="正在補齊行業分類")
        # Cache for everyone; network fetch only long+short passHard (5k Yahoo
        # profile calls stall refresh). Remaining labels backfill in background.
        # Short passers often fail the long gate, so long-only fetch left the
        # short heatmap stuck on 未分類.
        self._enrich_rows_with_profiles(rows, fetch_missing=False, quiet=True)
        priority = self._industry_priority_rows(rows, short_rows)
        self._enrich_rows_with_profiles(
            priority,
            fetch_missing=True,
            pass_hard_first=True,
            quiet=False,
        )
        self._set(progress=94, message="正在整理結果")
        self._sync_short_labels(rows, short_rows)
        rows.sort(key=lambda row: (-row["score"], row["symbol"]))
        short_rows.sort(key=lambda row: (-row["score"], row["symbol"]))
        snapshot = self._build_snapshot(
            rows=rows,
            rows_short=short_rows,
            spy_bars=spy_bars,
            source=source,
            universe_size=total,
            chart_failures=len(symbols) - chart_ok,
            partial=False,
        )
        criteria = snapshot["meta"].setdefault("criteria", {})
        criteria["industrySource"] = "yahoo-assetProfile"
        store.save_snapshot(snapshot, market=self.mid)
        store.prune_charts(set(symbols) | {self.market.benchmark}, market=self.mid)
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
        rows_short: list[dict] | None = None,
    ) -> dict:
        summary = summarize(rows)
        now = datetime.now(timezone.utc).isoformat()
        criteria = {
            "minMarketCap": self.market.min_market_cap,
            "marketCapCurrency": self.market.market_cap_currency,
            "nearHighWithin": 0.25,
            "closeAtSupportRuleVersion": RULE_VERSION,
            "scoreRuleVersion": SCORE_RULE_VERSION,
        }
        meta = {
            "refreshedAt": now,
            "marketDate": spy_bars[-1]["time"],
            "universeSource": source,
            "universe": {
                "unique": universe_size,
                "evaluated": len(rows),
                "partial": partial,
            },
            "summary": summary,
            "spy": spy_snapshot(spy_bars, symbol=self.market.benchmark),
            "benchmark": {
                "symbol": self.market.benchmark,
                "label": self.market.benchmark_label,
            },
            "market": self.mid,
            "side": "long",
            "source": "Yahoo Finance 圖表與報價（免費公開接口，無需 API 金鑰）",
            "dollarVolumeMethod": "優先取過去63個交易日的未還原收市價乘成交量之平均；不足則用三個月平均成交量乘現價。流動性只作評分，不作硬性門檻。",
            "adjustment": "K線及均線使用拆股還原價；成交額用未還原收市價乘成交量。",
            "marketCapNote": self.market.market_cap_note,
            "ttlHours": TTL_HOURS,
            "chartFailures": chart_failures,
            "criteria": criteria,
        }
        snapshot = {"meta": meta, "rows": rows}
        if rows_short is not None:
            criteria["shortRuleVersion"] = SHORT_RULE_VERSION
            meta["summaryShort"] = summarize(rows_short)
            snapshot["rowsShort"] = rows_short
        return snapshot

    def ensure_short_rows(self, snapshot: dict) -> dict:
        """Attach short-side rows computed from cached daily bars. Does not rewrite long rows."""
        rows = snapshot.get("rows") or []
        short_rows = snapshot.get("rowsShort")
        criteria = (snapshot.get("meta") or {}).get("criteria") or {}
        fresh = (
            isinstance(short_rows, list)
            and len(short_rows) == len(rows)
            and criteria.get("shortRuleVersion") == SHORT_RULE_VERSION
            and (not short_rows or "closeAtResistance" in short_rows[0])
        )
        if not fresh:
            self._build_short_rows(snapshot)
            short_rows = snapshot.get("rowsShort") or []
        self._sync_short_labels(rows, short_rows or [])
        return snapshot

    def _build_short_rows(self, snapshot: dict) -> None:
        """Recompute short rows from charts already stored for the long screen."""
        spy_bars = store.load_chart(self.market.benchmark, market=self.mid) or []
        updated: list[dict] = []
        for row in snapshot.get("rows") or []:
            bars = store.load_chart(row["symbol"], market=self.mid)
            quote = {
                "price": row.get("price"),
                "changePct": row.get("changePct"),
                "marketCap": row.get("marketCap"),
                "pe": row.get("pe"),
                "name": row.get("name"),
                "exchange": row.get("exchange"),
                "exchangeName": row.get("exchange"),
                "quoteType": "EQUITY" if "type" not in (row.get("failCodes") or []) else "ETF",
                "avgVolume3m": None,
                "sector": row.get("sectorEn") or row.get("sector"),
                "industry": row.get("industryEn") or row.get("industry"),
            }
            base = {
                "symbol": row["symbol"],
                "name": row.get("name") or row["symbol"],
                "nameZh": row.get("nameZh"),
                "groups": list(row.get("groups") or []),
                "sector": row.get("sectorEn") or row.get("sector"),
                "industry": row.get("industryEn") or row.get("industry"),
            }
            fresh = evaluate(
                base,
                bars,
                quote,
                spy_bars,
                side="short",
                detect_levels=False,
                **self._eval_kwargs(),
            )
            if fresh["passHard"]:
                apply_close_at_resistance(fresh, bars)
            updated.append(fresh)
        self._sync_short_labels(snapshot.get("rows") or [], updated)
        updated.sort(key=lambda item: (-item["score"], item["symbol"]))
        snapshot["rowsShort"] = updated
        meta = snapshot.setdefault("meta", {})
        meta["summaryShort"] = summarize(updated)
        criteria = meta.setdefault("criteria", {})
        criteria["shortRuleVersion"] = SHORT_RULE_VERSION
        store.save_snapshot(snapshot, market=self.mid)
        log.info("built short rows v%s count=%s pass=%s", SHORT_RULE_VERSION, len(updated), meta["summaryShort"]["pass"])

    def _sync_short_labels(self, long_rows: list[dict], short_rows: list[dict]) -> None:
        keys = (
            "name",
            "nameZh",
            "sector",
            "sectorEn",
            "industry",
            "industryEn",
            "groups",
            "groupLabels",
            "exchange",
            "pe",
        )
        by_symbol = {row["symbol"]: row for row in long_rows}
        for row in short_rows:
            src = by_symbol.get(row["symbol"])
            if not src:
                continue
            for key in keys:
                value = src.get(key)
                if value not in (None, "", []):
                    row[key] = value

    def prepare_snapshot(self) -> dict | None:
        """Load snapshot and apply one-shot backfills. Returns None when cache is empty."""
        snapshot = store.load_snapshot(self.mid)
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
            # FastAPI Cloud workers are short-lived; fill long+short passHard
            # synchronously so both heatmaps are correct on the same response,
            # then backfill the rest.
            priority = self._industry_priority_rows(
                snapshot.get("rows") or [],
                snapshot.get("rowsShort") or [],
            )
            missing_pass = [row for row in priority if self._row_needs_industry(row)]
            if missing_pass:
                self._enrich_rows_with_profiles(
                    missing_pass,
                    fetch_missing=True,
                    pass_hard_first=True,
                    quiet=True,
                )
                self._sync_short_labels(
                    snapshot.get("rows") or [],
                    snapshot.get("rowsShort") or [],
                )
                meta = snapshot.setdefault("meta", {})
                criteria = meta.setdefault("criteria", {})
                criteria["industrySource"] = "yahoo-assetProfile"
                store.save_snapshot(snapshot, market=self.mid)
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
        if self.mid == "hk":
            from app.universe_hk import apply_name_zh

            apply_name_zh(slim)
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
            bars = store.load_chart(row["symbol"], market=self.mid)
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
        store.save_snapshot(snapshot, market=self.mid)
        log.info("backfilled closeAtSupport v%s on %s cached rows", RULE_VERSION, len(snapshot["rows"]))

    def _backfill_score_rules(self, snapshot: dict) -> None:
        """Recompute Stage 2 rows (hard gates, score, RS) when score rules change."""
        spy_bars = store.load_chart(self.market.benchmark, market=self.mid) or []
        updated = []
        for row in snapshot["rows"]:
            bars = store.load_chart(row["symbol"], market=self.mid)
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
            fresh = evaluate(base, bars, quote, spy_bars, **self._eval_kwargs())
            for key in ("closeAtSupport", "closeAtSupportNote", "closeAtSupportLevel", "closeAtSupportTouches", "closeAtSupportZoneLow", "closeAtSupportZoneHigh", "revenueGrowth", "earningsGrowth", "profitMargin"):
                if key in row:
                    fresh[key] = row[key]
            updated.append(fresh)
        updated.sort(key=lambda item: (-item["score"], item["symbol"]))
        snapshot["rows"] = updated
        meta = snapshot.setdefault("meta", {})
        if spy_bars:
            meta["spy"] = spy_snapshot(spy_bars, symbol=self.market.benchmark)
            meta["benchmark"] = {
                "symbol": self.market.benchmark,
                "label": self.market.benchmark_label,
            }
            meta["market"] = self.mid
            meta["summary"] = summarize(updated)
        criteria = meta.setdefault("criteria", {})
        criteria["scoreRuleVersion"] = SCORE_RULE_VERSION
        criteria.pop("minBeta", None)
        criteria.pop("minDollarVolume", None)
        # Long recompute must not keep a short list scored against the previous rows.
        snapshot.pop("rowsShort", None)
        meta.pop("summaryShort", None)
        criteria.pop("shortRuleVersion", None)
        # Normalize universe meta shape for older snapshots.
        universe = meta.get("universe")
        if isinstance(universe, dict) and "unique" in universe and "evaluated" not in universe:
            universe["evaluated"] = len(updated)
            universe.setdefault("partial", False)
        store.save_snapshot(snapshot, market=self.mid)
        log.info("backfilled score rules v%s on %s cached rows", SCORE_RULE_VERSION, len(updated))

    def detail(self, symbol: str, interval: str = "1d", side: str = "long") -> dict:
        symbol = self.normalize_symbol(symbol)
        interval = normalize_interval(interval)
        side = normalize_side(side)
        bench = self.market.benchmark
        snapshot = store.load_snapshot(self.mid)
        row = None
        if snapshot:
            pool = snapshot.get("rows") or []
            if side == "short":
                criteria = (snapshot.get("meta") or {}).get("criteria") or {}
                short_pool = snapshot.get("rowsShort") or []
                if criteria.get("shortRuleVersion") == SHORT_RULE_VERSION and short_pool:
                    pool = short_pool
                else:
                    pool = []
            row = next((item for item in pool if item["symbol"] == symbol), None)
        client = get_client()
        quote = None
        if interval == "1d":
            bars = store.load_chart(symbol, market=self.mid)
            if bars is None or row is None:
                quote_map = client.quotes([symbol])
                quote = quote_map.get(symbol)
                if quote and quote.get("quoteType") not in (None, "EQUITY"):
                    raise LookupError(self.market.equity_only_message)
            if bars is None:
                bars = client.chart(symbol, interval="1d")
                if bars:
                    store.save_chart(symbol, bars, market=self.mid)
            spy = store.load_chart(bench, market=self.mid) or []
            if not spy:
                try:
                    spy = client.chart(bench, interval="1d") or []
                    if spy:
                        store.save_chart(bench, spy, market=self.mid)
                except Exception:
                    log.exception("failed to load %s chart for detail overlay", bench)
                    spy = []
        else:
            if row is None:
                quote_map = client.quotes([symbol])
                quote = quote_map.get(symbol)
                if quote and quote.get("quoteType") not in (None, "EQUITY"):
                    raise LookupError(self.market.equity_only_message)
            # Weekly/hourly always hit Yahoo — fetch symbol + benchmark in parallel.
            bars, spy = self._fetch_charts_parallel(client, symbol, interval)
        if not bars:
            raise LookupError("找不到這隻股份的圖表資料")
        eval_bars = bars
        eval_spy = spy
        if interval != "1d":
            daily = store.load_chart(symbol, market=self.mid)
            daily_spy = store.load_chart(bench, market=self.mid) or []
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
                "groups": [self.market.universe_group],
                "sector": None,
                "industry": None,
            }
            row = evaluate(
                base,
                eval_bars,
                quote or {},
                eval_spy,
                side=side,
                **self._eval_kwargs(),
            )
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
            if side == "short":
                matched_r, note_r, flagged_r = detect_close_at_resistance(bars)
                detail_row["closeAtResistance"] = matched_r
                detail_row["closeAtResistanceNote"] = note_r
                detail_row["closeAtResistanceLevel"] = round(flagged_r["price"], 2) if flagged_r else None
                detail_row["closeAtResistanceTouches"] = int(flagged_r["touches"]) if flagged_r else None
                detail_row["closeAtResistanceZoneLow"] = (
                    round(flagged_r["zoneLow"], 2) if flagged_r and flagged_r.get("zoneLow") is not None else None
                )
                detail_row["closeAtResistanceZoneHigh"] = (
                    round(flagged_r["zoneHigh"], 2) if flagged_r and flagged_r.get("zoneHigh") is not None else None
                )
                if matched_r and flagged_r:
                    levels = merge_flagged_resistance(levels, flagged_r)
        if self.mid == "hk":
            from app.universe_hk import apply_name_zh

            apply_name_zh([detail_row])
        notes = build_notes(
            detail_row,
            levels,
            benchmark_short=self.market.benchmark_short,
            currency=self.market.market_cap_currency,
            money_unit=self.market.money_unit,
            side=side,
        )
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
            "index": _index_series(spy, symbol=bench, label=self.market.benchmark_label),
            "levels": levels,
            "notes": notes,
            "profile": profile,
            "profilePending": profile_pending,
            "meta": None if snapshot is None else snapshot["meta"],
        }

    def profile(self, symbol: str) -> dict:
        """Secondary company profile fetch (may hit Yahoo). Does not block chart."""
        symbol = self.normalize_symbol(symbol)
        snapshot = store.load_snapshot(self.mid)
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
        notes = build_notes(
            detail_row,
            [],
            benchmark_short=self.market.benchmark_short,
            currency=self.market.market_cap_currency,
            money_unit=self.market.money_unit,
        )
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
                return client.chart(self.market.benchmark, interval=interval) or []
            except Exception:
                log.exception(
                    "failed to load %s %s chart for detail overlay",
                    self.market.benchmark,
                    interval,
                )
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
        cached = store.load_fundamentals(symbol, market=self.mid)
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
        existing = store.load_fundamentals(symbol, market=self.mid) or {}
        existing.pop("updatedAt", None)
        if profile.get("sector"):
            existing["sector"] = profile["sector"]
        if profile.get("industry"):
            existing["industry"] = profile["industry"]
        store.save_fundamentals(symbol, existing, market=self.mid)

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

    def _industry_priority_rows(self, rows: list[dict], short_rows: list[dict] | None = None) -> list[dict]:
        """Long-row objects that passed long and/or short Stage 2 (heatmap first)."""
        short_pass = {
            row["symbol"]
            for row in (short_rows or [])
            if row.get("passHard")
        }
        targets = [
            row
            for row in rows
            if row.get("passHard") or row.get("symbol") in short_pass
        ]
        return targets or list(rows)

    def _needs_industry_backfill(self, snapshot: dict) -> bool:
        rows = snapshot.get("rows") or []
        targets = self._industry_priority_rows(rows, snapshot.get("rowsShort") or [])
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
            name=f"kailut-industry-backfill-{self.mid}",
            daemon=True,
        ).start()
        return True

    def _run_industry_backfill(self) -> None:
        try:
            snapshot = store.load_snapshot(self.mid)
            if not snapshot:
                return
            rows = snapshot.get("rows") or []
            if not rows:
                return
            short_rows = snapshot.get("rowsShort") or []
            priority = self._industry_priority_rows(rows, short_rows)
            missing_pass = [row for row in priority if self._row_needs_industry(row)]
            log.info(
                "industry backfill start missing_priority=%s short_pass=%s",
                len(missing_pass),
                sum(1 for row in short_rows if row.get("passHard")),
            )
            # Fill long+short passHard first and persist so both heatmaps update.
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
                self._sync_short_labels(rows, short_rows)
                rows.sort(key=lambda row: (-row["score"], row["symbol"]))
                snapshot["rows"] = rows
                snapshot["rowsShort"] = short_rows
                meta = snapshot.setdefault("meta", {})
                criteria = meta.setdefault("criteria", {})
                criteria["industrySource"] = "yahoo-assetProfile"
                store.save_snapshot(snapshot, market=self.mid)
                log.info("industry backfill passHard filled=%s", filled_pass)
            # Then remaining evaluated rows from cache/Yahoo.
            filled_rest = self._enrich_rows_with_profiles(
                rows,
                fetch_missing=True,
                pass_hard_first=False,
                quiet=True,
            )
            self._sync_short_labels(rows, short_rows)
            rows.sort(key=lambda row: (-row["score"], row["symbol"]))
            snapshot["rows"] = rows
            snapshot["rowsShort"] = short_rows
            meta = snapshot.setdefault("meta", {})
            criteria = meta.setdefault("criteria", {})
            criteria["industrySource"] = "yahoo-assetProfile"
            store.save_snapshot(snapshot, market=self.mid)
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
        cached = store.load_fundamentals(symbol, market=self.mid)
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
            store.save_fundamentals(symbol, fresh, market=self.mid)
            return fresh
        return cached


    def normalize_symbol(self, symbol: str) -> str:
        raw = symbol.strip().upper()
        if self.mid == "hk":
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                raise ValueError("代號格式不正確")
            try:
                num = int(digits)
            except ValueError as exc:
                raise ValueError("代號格式不正確") from exc
            cleaned = f"{num:04d}.HK"
            if not HK_SYMBOL_RE.fullmatch(cleaned):
                raise ValueError("代號格式不正確")
            return cleaned
        cleaned = raw.replace(".", "-")
        if not US_SYMBOL_RE.fullmatch(cleaned):
            raise ValueError("代號格式不正確")
        return cleaned


def normalize_symbol(symbol: str, market: str = "us") -> str:
    return engines[market].normalize_symbol(symbol)


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


def cooldown_block(force: bool, market: str = "us") -> str | None:
    if force:
        return None
    snapshot = store.load_snapshot(market)
    if snapshot is None:
        return None
    age = store.age_seconds(snapshot)
    if age is not None and age < COOLDOWN_SECONDS:
        return "剛剛更新過，請五分鐘後再試"
    return None


engine = Engine(US_MARKET)
engine_hk = Engine(HK_MARKET)
engines = {"us": engine, "hk": engine_hk}
