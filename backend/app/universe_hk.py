"""Hong Kong equity universe from the official HKEX List of Securities.

Source XLS:
https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx

Traditional Chinese short names (keyless JSON):
https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json
Items like {"c":"00700","n":"騰訊控股",...} — c is 5-digit code, n is TC short name.
Mapped to Yahoo as XXXX.HK via last 4 digits / zfill (00001→0001.HK, 00700→0700.HK).

Keeps ordinary Equity Securities on Main Board / GEM. Excludes ETFs, warrants,
CBBCs, rights, bonds/debt, REITs, depositary receipts, investment companies,
and trading-only names when identifiable from Category / Sub-Category.
Yahoo symbols are 4-digit + .HK (e.g. 0700.HK).
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
from datetime import datetime, timezone

import httpx
from openpyxl import load_workbook

from app.config import DATA_DIR, USER_AGENT

log = logging.getLogger("kailut")

HKEX_LIST_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
)
HKEX_ZH_NAMES_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json"
UNIVERSE_PATH = DATA_DIR / "universe_hk.json"
NAMES_ZH_PATH = DATA_DIR / "hk_names_zh.json"

KEEP_SUB = frozenset(
    {
        "Equity Securities (Main Board)",
        "Equity Securities (GEM)",
    }
)

EXCLUDE_NAME_RE = re.compile(
    r"("
    r"\bETF\b|"
    r"\bREIT\b|"
    r"\bWarrant|"
    r"\bCBBC\b|"
    r"Callable Bull|"
    r"\bRight\b|"
    r"\bRights\b|"
    r"Depositary|"
    r"\bADR\b|"
    r"\bBond\b|"
    r"\bNote\b|"
    r"Preference"
    r")",
    re.IGNORECASE,
)

_zh_lock = threading.Lock()
_zh_map: dict[str, str] | None = None


def to_yahoo(stock_code: str) -> str | None:
    raw = str(stock_code or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    try:
        num = int(digits)
    except ValueError:
        return None
    if num <= 0 or num > 9999:
        return None
    return f"{num:04d}.HK"


def parse_list_of_securities(content: bytes) -> list[dict]:
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb[wb.sheetnames[0]]
    header_row = None
    for index, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        if row and str(row[0] or "").strip() == "Stock Code":
            header_row = index
            break
    if header_row is None:
        raise RuntimeError("HKEX 證券名單找不到表頭")

    rows: list[dict] = []
    seen: set[str] = set()
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not row or row[0] is None:
            continue
        category = str(row[2] or "").strip()
        sub = str(row[3] or "").strip()
        name = str(row[1] or "").strip()
        if category != "Equity":
            continue
        if sub not in KEEP_SUB:
            continue
        if EXCLUDE_NAME_RE.search(name or ""):
            continue
        yahoo = to_yahoo(str(row[0]))
        if not yahoo or yahoo in seen:
            continue
        seen.add(yahoo)
        venue = "hk-main" if "Main Board" in sub else "hk-gem"
        rows.append(
            {
                "symbol": yahoo,
                "name": name or yahoo,
                "sector": None,
                "industry": None,
                "groups": ["hk"],
                "venue": venue,
            }
        )
    rows.sort(key=lambda item: item["symbol"])
    if len(rows) < 500:
        raise RuntimeError(f"港股股票池過少（{len(rows)}），拒絕覆寫")
    return rows


def parse_zh_names(payload: list | dict) -> dict[str, str]:
    """Map Yahoo symbol → Traditional Chinese short name from HKEXnews JSON."""
    items = payload if isinstance(payload, list) else payload.get("data") or payload.get("table") or []
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("n") or "").strip()
        yahoo = to_yahoo(str(item.get("c") or ""))
        if not yahoo or not name:
            continue
        out[yahoo] = name
    return out


def fetch_zh_name_map() -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,*/*",
    }
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        response = client.get(HKEX_ZH_NAMES_URL)
        response.raise_for_status()
        payload = response.json()
    mapping = parse_zh_names(payload)
    if len(mapping) < 500:
        raise RuntimeError(f"港股中文名稱過少（{len(mapping)}），拒絕覆寫")
    return mapping


def save_zh_name_map(mapping: dict[str, str]) -> None:
    NAMES_ZH_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asOf": datetime.now(timezone.utc).date().isoformat(),
        "source": "hkexnews-activestock-sehk-c",
        "names": mapping,
    }
    NAMES_ZH_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _read_zh_name_map_file() -> dict[str, str]:
    if not NAMES_ZH_PATH.exists():
        return {}
    try:
        payload = json.loads(NAMES_ZH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    names = payload.get("names") if isinstance(payload, dict) else None
    if isinstance(names, dict):
        return {str(k): str(v) for k, v in names.items() if k and v}
    return {}


def refresh_zh_name_map() -> dict[str, str]:
    """Fetch HKEXnews TC names, persist, and update the in-memory cache."""
    global _zh_map
    mapping = fetch_zh_name_map()
    save_zh_name_map(mapping)
    with _zh_lock:
        _zh_map = mapping
    log.info("HK Chinese name map refreshed count=%s", len(mapping))
    return mapping


def load_zh_name_map(*, refresh: bool = False) -> dict[str, str]:
    """Return symbol→nameZh map. Prefer memory, then disk; optionally refresh from HKEXnews."""
    global _zh_map
    if refresh:
        try:
            return refresh_zh_name_map()
        except Exception:
            log.exception("HK Chinese name refresh failed; falling back to cache")
    with _zh_lock:
        if _zh_map is not None:
            return _zh_map
    cached = _read_zh_name_map_file()
    if cached:
        with _zh_lock:
            _zh_map = cached
        return cached
    try:
        return refresh_zh_name_map()
    except Exception:
        log.exception("HK Chinese name map unavailable")
        with _zh_lock:
            _zh_map = {}
        return {}


def apply_name_zh(rows: list[dict], name_map: dict[str, str] | None = None) -> list[dict]:
    """Stamp nameZh onto each row from the cached HKEXnews map (in-place)."""
    if not rows:
        return rows
    mapping = name_map if name_map is not None else load_zh_name_map()
    if not mapping:
        return rows
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        zh = mapping.get(symbol)
        if zh:
            row["nameZh"] = zh
    return rows


def attach_zh_names(rows: list[dict], *, refresh: bool = False) -> list[dict]:
    """Join Chinese short names onto universe / screen rows."""
    return apply_name_zh(rows, load_zh_name_map(refresh=refresh))


def fetch_universe() -> list[dict]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
    }
    with httpx.Client(headers=headers, timeout=90.0, follow_redirects=True) as client:
        response = client.get(HKEX_LIST_URL)
        response.raise_for_status()
        content = response.content
    if content[:2] != b"PK":
        raise RuntimeError("HKEX 證券名單不是有效的 XLSX")
    rows = parse_list_of_securities(content)
    try:
        attach_zh_names(rows, refresh=True)
    except Exception:
        log.exception("attaching HK Chinese names during universe fetch failed")
        attach_zh_names(rows, refresh=False)
    return rows


def save_universe(rows: list[dict]) -> None:
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asOf": datetime.now(timezone.utc).date().isoformat(),
        "source": "hkex-list-of-securities",
        "symbols": rows,
    }
    UNIVERSE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_fallback() -> list[dict]:
    if not UNIVERSE_PATH.exists():
        return []
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    rows = payload.get("symbols") or []
    attach_zh_names(rows, refresh=False)
    return rows


def load_universe() -> tuple[list[dict], str]:
    try:
        rows = fetch_universe()
        if rows:
            save_universe(rows)
            return rows, "hkex-list-of-securities"
    except Exception:
        fallback = load_fallback()
        if fallback:
            return fallback, "cache"
        raise
    fallback = load_fallback()
    if fallback:
        return fallback, "cache"
    raise RuntimeError("未能取得港股證券名單")
