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

from app.engine import cooldown_block, engine
from app import screen_cache, store
from app.strategies import STRATEGIES, get_strategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kailut")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    snapshot = store.load_snapshot()
    if snapshot is None or store.is_stale(snapshot):
        log.info("cache missing or stale; starting refresh")
        engine.start()
    elif engine._needs_industry_backfill(snapshot):
        log.info("screen cache missing industry labels; starting backfill")
        engine.start_industry_backfill()
    if snapshot is not None:
        try:
            screen_cache.rebuild(snapshot, engine.status(), store.is_stale(snapshot))
        except Exception as exc:
            log.warning("startup screen cache rebuild failed: %s", exc)
    yield


app = FastAPI(title="階律", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "name": "階律"}


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
    snapshot = engine.prepare_snapshot()
    refresh = engine.status()
    if snapshot is None:
        return {"ready": False, "stale": False, "meta": None, "rows": [], "refresh": refresh}
    stale = store.is_stale(snapshot)
    # Prefer pre-gzipped wire cache rebuilt on save_snapshot; serve bytes fast.
    return screen_cache.response(
        snapshot=snapshot,
        refresh=refresh,
        stale=stale,
        include=include,
        accept_encoding=request.headers.get("accept-encoding"),
    )


@app.post("/api/refresh")
def refresh(force: bool = Query(default=False)):
    reason = cooldown_block(force)
    if reason and not engine.status()["running"]:
        return {"started": False, "reason": "cooldown", "message": reason, "refresh": engine.status()}
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
