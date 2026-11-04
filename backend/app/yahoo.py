"""Yahoo Finance public endpoints. No API key.

Chart history uses the v8 chart API. Quotes and fundamentals need the
cookie + crumb flow that the site itself uses.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.config import USER_AGENT

NY = ZoneInfo("America/New_York")


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _raw(value) -> float | None:
    if isinstance(value, dict):
        return _number(value.get("raw"))
    return _number(value)


def normalize_quote(payload: dict) -> dict:
    change = _number(payload.get("regularMarketChangePercent"))
    if change is not None:
        change /= 100.0
    pe = _number(payload.get("trailingPE"))
    if pe is not None and (pe <= 0 or pe > 5000):
        pe = None
    market_cap = _number(payload.get("marketCap"))
    if market_cap is not None and market_cap <= 0:
        market_cap = None
    return {
        "price": _number(payload.get("regularMarketPrice")),
        "changePct": change,
        "marketCap": market_cap,
        "avgVolume3m": _number(payload.get("averageDailyVolume3Month")),
        "pe": pe,
        "name": payload.get("longName") or payload.get("shortName"),
        "exchange": payload.get("exchange"),
        "exchangeName": payload.get("fullExchangeName"),
        "quoteType": payload.get("quoteType"),
        "marketTime": payload.get("regularMarketTime"),
        "currency": payload.get("currency"),
    }


# Chart interval -> Yahoo query. Weekly uses 5y so SMA200 (200 weeks) can form.
# Hourly uses 60d (Yahoo's practical 1h window); SMA50/200 stay bar-count windows.
CHART_INTERVALS = {
    "1d": {"interval": "1d", "range": "2y", "intraday": False},
    "1wk": {"interval": "1wk", "range": "5y", "intraday": False},
    "1h": {"interval": "1h", "range": "60d", "intraday": True},
}


def normalize_interval(interval: str | None) -> str:
    key = (interval or "1d").strip().lower()
    aliases = {"d": "1d", "day": "1d", "daily": "1d", "w": "1wk", "wk": "1wk", "week": "1wk", "weekly": "1wk", "h": "1h", "hour": "1h", "hourly": "1h", "1hour": "1h"}
    key = aliases.get(key, key)
    if key not in CHART_INTERVALS:
        raise ValueError("不支援這個週期（可用 1d、1wk、1h）")
    return key


def parse_chart(payload: dict, *, intraday: bool = False) -> list[dict] | None:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    block = result[0]
    timestamps = block.get("timestamp") or []
    quote_block = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    opens = quote_block.get("open") or []
    highs = quote_block.get("high") or []
    lows = quote_block.get("low") or []
    closes = quote_block.get("close") or []
    volumes = quote_block.get("volume") or []
    merged: dict[str | int, dict] = {}
    for index, ts in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        open_ = opens[index] if index < len(opens) else None
        high = highs[index] if index < len(highs) else None
        low = lows[index] if index < len(lows) else None
        volume = volumes[index] if index < len(volumes) else 0
        if None in (close, open_, high, low):
            continue
        if min(close, open_, high, low) <= 0 or high < low:
            continue
        adj = adjusted[index] if index < len(adjusted) else None
        factor = 1.0
        if adj and close:
            factor = adj / close
            if factor <= 0 or factor > 1000 or factor < 0.001:
                continue
        stamp = int(ts)
        share_volume = float(volume or 0)
        # Intraday: unix seconds for lightweight-charts; daily/weekly: YYYY-MM-DD.
        if intraday:
            key: str | int = stamp
            time_value: str | int = stamp
        else:
            day = datetime.fromtimestamp(stamp, NY).date().isoformat()
            key = day
            time_value = day
        merged[key] = {
            "time": time_value,
            "open": open_ * factor,
            "high": high * factor,
            "low": low * factor,
            "close": close * factor,
            "volume": share_volume,
            "dollar": close * share_volume,
        }
    if not merged:
        return None
    return [merged[key] for key in sorted(merged)]


class YahooClient:
    def __init__(self) -> None:
        self._local = threading.local()
        self._crumb: str | None = None
        self._crumb_lock = threading.Lock()
        self._main = self._new_client()

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    def _chart_client(self) -> httpx.Client:
        client = getattr(self._local, "client", None)
        if client is None:
            client = self._new_client()
            self._local.client = client
        return client

    def _ensure_crumb(self) -> None:
        with self._crumb_lock:
            if self._crumb:
                return
            try:
                self._main.get("https://fc.yahoo.com")
            except httpx.HTTPError:
                pass
            response = self._main.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
            response.raise_for_status()
            self._crumb = response.text.strip().strip('"')
            if not self._crumb or self._crumb.startswith("<"):
                raise RuntimeError("未能取得 Yahoo crumb")

    def _get(self, client: httpx.Client, url: str, params: dict | None = None, auth: bool = False):
        for attempt in range(4):
            query = dict(params or {})
            if auth:
                try:
                    self._ensure_crumb()
                except Exception:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                query["crumb"] = self._crumb
            try:
                response = client.get(url, params=query)
            except httpx.HTTPError:
                time.sleep(0.4 * (attempt + 1))
                continue
            if response.status_code in (401, 403) and auth:
                with self._crumb_lock:
                    self._crumb = None
                time.sleep(0.3 * (attempt + 1))
                continue
            if response.status_code in (429, 500, 502, 503):
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code >= 400:
                return None
            return response
        return None

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for start in range(0, len(symbols), 80):
            chunk = symbols[start : start + 80]
            response = self._get(
                self._main,
                "https://query1.finance.yahoo.com/v7/finance/quote",
                params={"symbols": ",".join(chunk)},
                auth=True,
            )
            if response is None:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            for item in (payload.get("quoteResponse") or {}).get("result") or []:
                symbol = item.get("symbol")
                if symbol:
                    found[symbol] = normalize_quote(item)
        return found

    def chart(self, symbol: str, interval: str = "1d") -> list[dict] | None:
        interval = normalize_interval(interval)
        spec = CHART_INTERVALS[interval]
        response = self._get(
            self._chart_client(),
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='-')}",
            params={
                "interval": spec["interval"],
                "range": spec["range"],
                "includeAdjustedClose": "true",
                "events": "div,splits",
            },
        )
        if response is None:
            return None
        try:
            return parse_chart(response.json(), intraday=bool(spec["intraday"]))
        except ValueError:
            return None

    def charts(self, symbols: list[str], workers: int, on_each=None) -> dict[str, list[dict]]:
        found: dict[str, list[dict]] = {}
        lock = threading.Lock()

        def job(symbol: str) -> None:
            bars = None
            try:
                bars = self.chart(symbol)
            except Exception:
                bars = None
            with lock:
                if bars:
                    found[symbol] = bars
            if on_each:
                on_each(symbol, bool(bars))

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(job, symbols))
        return found

    def vendor_beta(self, symbol: str) -> float | None:
        response = self._get(
            self._main,
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{quote(symbol, safe='-')}",
            params={"modules": "defaultKeyStatistics"},
            auth=True,
        )
        if response is None:
            return None
        try:
            result = (response.json().get("quoteSummary") or {}).get("result") or []
        except ValueError:
            return None
        if not result:
            return None
        raw = (result[0].get("defaultKeyStatistics") or {}).get("beta")
        number = _raw(raw)
        if number is None or abs(number) > 8:
            return None
        return number

    def betas(self, symbols: list[str], workers: int = 8) -> dict[str, float]:
        found: dict[str, float] = {}
        lock = threading.Lock()

        def job(symbol: str) -> None:
            try:
                value = self.vendor_beta(symbol)
            except Exception:
                value = None
            if value is None:
                return
            with lock:
                found[symbol] = value

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(job, symbols))
        return found

    def fundamentals(self, symbol: str) -> dict | None:
        response = self._get(
            self._main,
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{quote(symbol, safe='-')}",
            params={"modules": "financialData,assetProfile,defaultKeyStatistics"},
            auth=True,
        )
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        result = (payload.get("quoteSummary") or {}).get("result") or []
        if not result:
            return None
        block = result[0]
        profile = block.get("assetProfile") or {}
        financials = block.get("financialData") or {}
        stats = block.get("defaultKeyStatistics") or {}
        pe = _raw(stats.get("trailingPE"))
        if pe is not None and (pe <= 0 or pe > 5000):
            pe = None
        employees = profile.get("fullTimeEmployees")
        if isinstance(employees, bool) or not isinstance(employees, (int, float)):
            employees = None
        else:
            employees = int(employees)
            if employees <= 0:
                employees = None
        def _text(value) -> str | None:
            if not isinstance(value, str):
                return None
            cleaned = value.strip()
            return cleaned or None

        website = _text(profile.get("website"))
        city = _text(profile.get("city"))
        state = _text(profile.get("state"))
        country = _text(profile.get("country"))
        phone = _text(profile.get("phone"))
        summary = _text(profile.get("longBusinessSummary"))
        hq_parts = [part for part in (city, state, country) if part]
        return {
            "sector": profile.get("sector") or None,
            "industry": profile.get("industry") or None,
            "summary": summary,
            "website": website,
            "employees": employees,
            "city": city,
            "state": state,
            "country": country,
            "phone": phone,
            "hq": ", ".join(hq_parts) if hq_parts else None,
            "revenueGrowth": _raw(financials.get("revenueGrowth")),
            "earningsGrowth": _raw(financials.get("earningsGrowth")),
            "profitMargin": _raw(financials.get("profitMargins")),
            "pe": pe,
        }


_client: YahooClient | None = None
_client_lock = threading.Lock()


def get_client() -> YahooClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = YahooClient()
        return _client
