"""Hong Kong equity universe from the official HKEX List of Securities.

Source XLS:
https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx

Keeps ordinary Equity Securities on Main Board / GEM. Excludes ETFs, warrants,
CBBCs, rights, bonds/debt, REITs, depositary receipts, investment companies,
and trading-only names when identifiable from Category / Sub-Category.
Yahoo symbols are 4-digit + .HK (e.g. 0700.HK).
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from openpyxl import load_workbook

from app.config import DATA_DIR, USER_AGENT

HKEX_LIST_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
)
UNIVERSE_PATH = DATA_DIR / "universe_hk.json"

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
    return parse_list_of_securities(content)


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
    return payload.get("symbols") or []


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
