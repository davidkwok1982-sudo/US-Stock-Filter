"""階律 HTTP API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.engine import cooldown_block, engine, engine_hk, engines
from app import screen_cache, store
from app.strategies import STRATEGIES, get_strategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kailut")


def _boot_market(market: str) -> None:
    store.init_db(market)
    eng = engines[market]
    snapshot = store.load_snapshot(market)
    if snapshot is None or store.is_stale(snapshot):
        # Hobby / ephemeral disk: do not auto-start a full refresh on cold boot
        # for either market. An empty cache shows 「請按重新整理」; a stale cache
        # stays on screen until the user presses 重新整理.
        log.info("%s cache missing or stale; waiting for manual refresh", market)
    elif eng._needs_industry_backfill(snapshot):
        log.info("%s screen cache missing industry labels; starting backfill", market)
        eng.start_industry_backfill()
    if snapshot is not None:
        try:
            screen_cache.rebuild(snapshot, eng.status(), store.is_stale(snapshot), market=market)
        except Exception as exc:
            log.warning("startup screen cache rebuild failed (%s): %s", market, exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _boot_market("us")
    _boot_market("hk")
    yield


app = FastAPI(title="階律", lifespan=lifespan)
# compresslevel=1 for any non-precompressed JSON. Starlette skips responses that
# already set Content-Encoding (our /api/screen pre-gzip path), so no double-gzip.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "name": "階律",
        "markets": {
            "us": {"ready": store.load_snapshot("us") is not None, "refresh": engine.status()},
            "hk": {"ready": store.load_snapshot("hk") is not None, "refresh": engine_hk.status()},
        },
    }


@app.get("/api/strategies")
def strategies():
    return {"strategies": STRATEGIES}


@app.get("/api/screen")
def screen(
    request: Request,
    strategy: str = "jlaw-stage2",
    include: str = Query(default="pass", pattern="^(pass|all)$"),
):
    """Default: passHard rows + meta.summary. Pass ?include=all for the full universe."""
    chosen = get_strategy(strategy)
    if chosen is None:
        raise HTTPException(status_code=404, detail="沒有這個策略")
    if chosen["status"] != "active":
        raise HTTPException(status_code=501, detail="此策略尚未推出")
    refresh = engine.status()
    accept_encoding = request.headers.get("accept-encoding")
    # Hot path: warm pre-gzip cache → status() only (no SQLite / row scans).
    cached_snap = screen_cache.get_cached_snapshot(market="us")
    if cached_snap is not None and (
        screen_cache.has_entry(include, market="us")
        or (include == "all" and screen_cache.has_entry("pass", market="us"))
    ):
        stale = store.is_stale(cached_snap)
        warm = screen_cache.try_warm_response(
            include=include,
            refresh=refresh,
            stale=stale,
            accept_encoding=accept_encoding,
            market="us",
        )
        if warm is not None:
            return warm
    # Miss / empty after deploy / first request: load + backfill, then rebuild cache.
    snapshot = engine.prepare_snapshot()
    if snapshot is None:
        return {
            "ready": False,
            "stale": False,
            "meta": {
                "market": "us",
                "hint": "美股快取尚未建立。請按「重新整理」建立股票池。",
            },
            "rows": [],
            "refresh": refresh,
        }
    stale = store.is_stale(snapshot)
    return screen_cache.response(
        snapshot=snapshot,
        refresh=refresh,
        stale=stale,
        include=include,
        accept_encoding=accept_encoding,
        market="us",
    )


@app.post("/api/refresh")
def refresh(force: bool = Query(default=False)):
    reason = cooldown_block(force)
    if reason and not engine.status()["running"]:
        return {"started": False, "reason": "cooldown", "message": reason, "refresh": engine.status()}
    if engine_hk.status()["running"] and not engine.status()["running"]:
        return {
            "started": False,
            "reason": "busy",
            "message": "港股全量更新進行中，Hobby 實例負荷已滿。請等港股完成後再更新美股。",
            "refresh": engine.status(),
        }
    started = engine.start()
    return {
        "started": started,
        "reason": "started" if started else "running",
        "message": "已開始更新" if started else "更新進行中",
        "refresh": engine.status(),
    }



@app.get("/api/stock/{symbol}/profile")
def stock_profile(symbol: str):
    """Company profile / fundamentals — may hit Yahoo; keep off the chart critical path."""
    try:
        return engine.profile(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/stock/{symbol}")
def stock(symbol: str, interval: str = Query(default="1d", description="Chart timeframe: 1d, 1wk, or 1h")):
    try:
        return engine.detail(symbol, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



def _hk_screen_response(request: Request, include: str):
    refresh = engine_hk.status()
    accept_encoding = request.headers.get("accept-encoding")
    cached_snap = screen_cache.get_cached_snapshot(market="hk")
    if cached_snap is not None and (
        screen_cache.has_entry(include, market="hk")
        or (include == "all" and screen_cache.has_entry("pass", market="hk"))
    ):
        stale = store.is_stale(cached_snap)
        warm = screen_cache.try_warm_response(
            include=include,
            refresh=refresh,
            stale=stale,
            accept_encoding=accept_encoding,
            market="hk",
        )
        if warm is not None:
            return warm
    snapshot = engine_hk.prepare_snapshot()
    if snapshot is None:
        return {
            "ready": False,
            "stale": False,
            "meta": {
                "market": "hk",
                "hint": "港股快取尚未建立。Hobby 部署為臨時磁碟，請先按「重新整理」或呼叫 POST /api/hk/refresh。",
            },
            "rows": [],
            "refresh": refresh,
        }
    stale = store.is_stale(snapshot)
    return screen_cache.response(
        snapshot=snapshot,
        refresh=refresh,
        stale=stale,
        include=include,
        accept_encoding=accept_encoding,
        market="hk",
    )


@app.get("/api/hk/screen")
def hk_screen(
    request: Request,
    strategy: str = "jlaw-stage2",
    include: str = Query(default="pass", pattern="^(pass|all)$"),
):
    chosen = get_strategy(strategy)
    if chosen is None:
        raise HTTPException(status_code=404, detail="沒有這個策略")
    if chosen["status"] != "active":
        raise HTTPException(status_code=501, detail="此策略尚未推出")
    return _hk_screen_response(request, include)


@app.post("/api/hk/refresh")
def hk_refresh(force: bool = Query(default=False)):
    reason = cooldown_block(force, market="hk")
    if reason and not engine_hk.status()["running"]:
        return {"started": False, "reason": "cooldown", "message": reason, "refresh": engine_hk.status()}
    if engine.status()["running"] and not engine_hk.status()["running"]:
        return {
            "started": False,
            "reason": "busy",
            "message": "美股全量更新進行中，Hobby 實例負荷已滿。請等美股完成後再更新港股。",
            "refresh": engine_hk.status(),
        }
    started = engine_hk.start()
    return {
        "started": started,
        "reason": "started" if started else "running",
        "message": "已開始更新" if started else "更新進行中",
        "refresh": engine_hk.status(),
    }


@app.get("/api/hk/stock/{symbol}/profile")
def hk_stock_profile(symbol: str):
    try:
        return engine_hk.profile(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/hk/stock/{symbol}")
def hk_stock(symbol: str, interval: str = Query(default="1d", description="Chart timeframe: 1d, 1wk, or 1h")):
    try:
        return engine_hk.detail(symbol, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Serve Vite build for non-/api routes (FastAPI Cloud / Render / local all-in-one).
# Prefer dist/ next to the Python deploy root (backend/dist); fall back to static/ (Docker).
# Mount AFTER API routes so /api/* keeps FastAPI handlers. Missing dir = API-only (compose).
_backend_root = Path(__file__).resolve().parents[1]
_default_static = _backend_root / "dist"
if not _default_static.is_dir():
    _default_static = _backend_root / "static"
_STATIC_DIR = Path(os.environ.get("KAI_LUT_STATIC", str(_default_static)))
if _STATIC_DIR.is_dir():
    # SPA: serve built files, and fall back to index.html for client routes like /stock/AAPL.
    # app.frontend(..., fallback=...) has been unreliable on FastAPI Cloud for nested paths.
    _assets_dir = _STATIC_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (_STATIC_DIR / full_path).resolve()
        try:
            candidate.relative_to(_STATIC_DIR.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not Found") from exc
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = _STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Not Found")
