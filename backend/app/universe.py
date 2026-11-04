"""Broad US equity universe from Nasdaq Trader symbol directories.

Live lists (no API key):
- https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
- https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt

Keeps US-listed ordinary/common shares; excludes ETF/ETN/NextShares, ADR/ADS,
test issues, warrants, units, preferred, and rights when clearly flagged.
A JSON snapshot in data/universe.json is refreshed on success and used if download fails.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx

from app.config import UNIVERSE_PATH, USER_AGENT

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# otherlisted Exchange column: N=NYSE, A=NYSE American, P=NYSE Arca, Z=BATS, V=IEX
US_EXCHANGES = frozenset({"N", "A", "P", "Z", "V"})

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

EXCLUDE_NAME_RE = re.compile(
    r"("
    r"American Depositary|"
    r"\bADS\b|"
    r"\bADR\b|"
    r"Depositary Share|"
    r"New York Registry|"
    r"Registry Share|"
    r"\bETF\b|"
    r"\bETN\b|"
    r"Exchange[- ]Traded|"
    r"NextShares|"
    r"\bWarrant|"
    r"\bWarrants\b|"
    r"\bUnit\b|"
    r"\bUnits\b|"
    r"Preferred|"
    r"Preference Share|"
    r"\bRight\b|"
    r"\bRights\b|"
    r"\bNote\b|"
    r"\bNotes\b|"
    r"\bBond\b|"
    r"\bBonds\b|"
    r"Debenture|"
    r"Test Issue|"
    r"Trust Preferred|"
    r"Structured Product"
    r")",
    re.IGNORECASE,
)

# Foreign entity forms often used by ADRs that omit "Depositary" in the Nasdaq name.
FOREIGN_ENTITY_RE = re.compile(
    r"\b(N\.V\.|S\.A\.B?\b|S\.A\.|Ltd\.?|Limited|PLC|AG\b|SE\b|KGaA|S\.p\.A\.)",
    re.IGNORECASE,
)
COMMON_EQUITY_RE = re.compile(
    r"(Common Stock|Ordinary Share|Ordinary Shares|Capital Stock|Class [A-Z] (Common|Ordinary))",
    re.IGNORECASE,
)


def to_yahoo(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def _is_excluded_name(name: str) -> bool:
    text = name or ""
    if EXCLUDE_NAME_RE.search(text):
        return True
    # e.g. TSM is listed without "Depositary" but as a foreign Ltd. with no common-stock marker.
    if FOREIGN_ENTITY_RE.search(text) and not COMMON_EQUITY_RE.search(text):
        return True
    return False


def _valid_symbol(raw: str) -> str | None:
    symbol = (raw or "").strip().upper()
    if not symbol or "$" in symbol or "^" in symbol or "/" in symbol:
        return None
    if not SYMBOL_RE.fullmatch(symbol):
        return None
    return symbol


def parse_nasdaq_listed(text: str) -> list[dict]:
    """Parse nasdaqlisted.txt into candidate rows (pre-merge)."""
    rows: list[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("Symbol|") or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        symbol, name, _cat, test_issue, _status, _lot, etf, next_shares = parts[:8]
        if test_issue == "Y" or etf == "Y" or next_shares == "Y":
            continue
        if _is_excluded_name(name):
            continue
        cleaned = _valid_symbol(symbol)
        if not cleaned:
            continue
        rows.append(
            {
                "symbol": cleaned,
                "name": (name or cleaned).strip(),
                "sector": None,
                "industry": None,
                "group": "us",
                "venue": "nasdaq",
            }
        )
    return rows


def parse_other_listed(text: str) -> list[dict]:
    """Parse otherlisted.txt into candidate rows (pre-merge)."""
    rows: list[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("ACT Symbol|") or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        act_symbol, name, exchange, _cqs, etf, _lot, test_issue, nasdaq_symbol = parts[:8]
        if test_issue == "Y" or etf == "Y":
            continue
        if exchange not in US_EXCHANGES:
            continue
        if _is_excluded_name(name):
            continue
        raw = (nasdaq_symbol or act_symbol or "").strip()
        cleaned = None
        if raw:
            # NASDAQ Symbol often already Yahoo-style (BRK-B); ACT may use BRK.B.
            if re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", raw.upper()) and "$" not in raw:
                cleaned = raw.upper()
            else:
                cleaned = _valid_symbol(raw)
        if cleaned is None:
            cleaned = _valid_symbol(act_symbol)
        if not cleaned:
            continue
        rows.append(
            {
                "symbol": cleaned,
                "name": (name or cleaned).strip(),
                "sector": None,
                "industry": None,
                "group": "us",
                "venue": {"N": "nyse", "A": "amex", "P": "arca", "Z": "bats", "V": "iex"}.get(
                    exchange, "other"
                ),
            }
        )
    return rows


def _merge(items: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in items:
        yahoo = to_yahoo(item["symbol"])
        if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", yahoo):
            continue
        if yahoo in merged:
            continue
        merged[yahoo] = {
            "symbol": yahoo,
            "name": item.get("name") or yahoo,
            "sector": item.get("sector"),
            "industry": item.get("industry"),
            "groups": ["us"],
            "venue": item.get("venue"),
        }
    rows = list(merged.values())
    rows.sort(key=lambda row: row["symbol"])
    return rows


def _download(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    text = response.text
    if "Symbol|" not in text and "ACT Symbol|" not in text:
        raise RuntimeError(f"符號目錄格式異常：{url}")
    return text


def fetch_universe() -> list[dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        nasdaq_text = _download(client, NASDAQ_LISTED)
        other_text = _download(client, OTHER_LISTED)
    nasdaq_rows = parse_nasdaq_listed(nasdaq_text)
    other_rows = parse_other_listed(other_text)
    rows = _merge(nasdaq_rows + other_rows)
    if len(rows) < 1000:
        raise RuntimeError(f"美股宇宙過少（{len(rows)}），拒絕覆寫")
    return rows


def save_universe(rows: list[dict]) -> None:
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asOf": datetime.now(timezone.utc).date().isoformat(),
        "source": "nasdaq-trader",
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
            return rows, "nasdaq-trader"
    except Exception:
        fallback = load_fallback()
        if fallback:
            return fallback, "cache"
        raise
    fallback = load_fallback()
    if fallback:
        return fallback, "cache"
    raise RuntimeError("未能取得美股符號目錄")
