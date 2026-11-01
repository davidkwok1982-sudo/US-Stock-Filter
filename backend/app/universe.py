"""S&P 500, S&P MidCap 400, and Nasdaq-100 constituents.

Live lists come from Wikipedia wikitext. A JSON snapshot in data/universe.json
is refreshed whenever a live fetch succeeds, and used if Wikipedia is down.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx

from app.config import UNIVERSE_PATH, USER_AGENT

WIKI = "https://en.wikipedia.org/w/api.php"
PAGES = (
    ("sp500", "List of S&P 500 companies"),
    ("sp400", "List of S&P 400 companies"),
    ("ndx", "List of NASDAQ-100 companies"),
)
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def to_yahoo(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def _plain(cell: str) -> str:
    text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", cell)
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.replace("&amp;", "&").split())


def _symbol_from_cell(cell: str) -> str | None:
    matched = re.search(r"\{\{(?:Nyse|Nasdaq)Symbol\|([^}]+)\}\}", cell)
    if matched:
        return matched.group(1).strip()
    plain = _plain(cell).split()
    if not plain:
        return None
    token = plain[0].strip()
    if SYMBOL_RE.fullmatch(token):
        return token
    return None


def _split_cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|-"):
        body = body[2:].strip()
    if not body or body.startswith("!") or body.startswith("|}"):
        return []
    if "\n" not in body and "||" in body:
        parts = [part.strip() for part in body.split("||")]
        parts[0] = parts[0].lstrip("|").strip()
        return parts
    cells: list[str] = []
    buffer: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("||"):
            if buffer is not None:
                cells.append(buffer.strip())
            buffer = stripped[2:].strip()
        elif stripped.startswith("|") and not stripped.startswith("|}"):
            if buffer is not None:
                cells.append(buffer.strip())
            rest = stripped[1:].strip()
            if "|" in rest and re.match(r"(style|rowspan|colspan|align)=", rest):
                rest = rest.split("|", 1)[1].strip()
            buffer = rest
        elif buffer is not None:
            buffer = f"{buffer} {stripped}".strip()
    if buffer is not None:
        cells.append(buffer.strip())
    return cells


def parse_constituents(wikitext: str, group: str) -> list[dict]:
    marker = wikitext.find('id="constituents"')
    if marker < 0:
        marker = wikitext.find("constituents")
    section = wikitext[marker:] if marker >= 0 else wikitext
    end = section.find("\n|}")
    if end >= 0:
        section = section[:end]
    rows: list[dict] = []
    for raw in re.split(r"\n\|-", section):
        cells = _split_cells(raw)
        if len(cells) < 2:
            continue
        symbol = _symbol_from_cell(cells[0])
        if not symbol:
            continue
        name = _plain(cells[1]) or symbol
        # S&P tables are Symbol, Security, Sector, Sub-Industry.
        # Nasdaq-100 inserts an ISIN column, which becomes blank once templates are stripped.
        details = [text for text in (_plain(cell) for cell in cells[2:]) if text]
        sector = details[0] if details else ""
        industry = details[1] if len(details) > 1 else ""
        if sector.lower() in {"gics sector", "icb industry", "sector"}:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "sector": sector or None,
                "industry": industry or None,
                "group": group,
            }
        )
    return rows


def _fetch_wikitext(client: httpx.Client, page: str) -> str:
    response = client.get(
        WIKI,
        params={"action": "parse", "page": page, "prop": "wikitext", "format": "json"},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload["error"].get("info") or "Wikipedia 沒有這頁")
    return payload["parse"]["wikitext"]["*"]


def fetch_universe() -> list[dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=40.0, follow_redirects=True) as client:
        grouped = []
        for group, page in PAGES:
            text = _fetch_wikitext(client, page)
            parsed = parse_constituents(text, group)
            if len(parsed) < 50:
                raise RuntimeError(f"{page} 成份過少（{len(parsed)}）")
            grouped.extend(parsed)
    return _merge(grouped)


def _merge(items: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in items:
        yahoo = to_yahoo(item["symbol"])
        if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", yahoo):
            continue
        current = merged.get(yahoo)
        if current is None:
            merged[yahoo] = {
                "symbol": yahoo,
                "name": item["name"] or yahoo,
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "groups": [item["group"]],
            }
            continue
        if item["group"] not in current["groups"]:
            current["groups"].append(item["group"])
        if not current.get("sector") and item.get("sector"):
            current["sector"] = item["sector"]
            current["industry"] = item.get("industry")
    rows = list(merged.values())
    order = {"sp500": 0, "ndx": 1, "sp400": 2}
    for row in rows:
        row["groups"] = sorted(row["groups"], key=lambda name: order.get(name, 9))
    rows.sort(key=lambda row: row["symbol"])
    return rows


def save_universe(rows: list[dict]) -> None:
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asOf": datetime.now(timezone.utc).date().isoformat(),
        "source": "wikipedia",
        "symbols": rows,
    }
    UNIVERSE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_fallback() -> list[dict]:
    if not UNIVERSE_PATH.exists():
        return []
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    rows = payload.get("symbols") or []
    return rows


def load_universe() -> tuple[list[dict], str]:
    try:
        rows = fetch_universe()
        if rows:
            save_universe(rows)
            return rows, "wikipedia"
    except Exception:
        fallback = load_fallback()
        if fallback:
            return fallback, "cache"
        raise
    fallback = load_fallback()
    if fallback:
        return fallback, "cache"
    raise RuntimeError("未能取得指數成份")
