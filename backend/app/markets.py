"""Market-specific Stage 2 screening configuration (US vs HK)."""

from __future__ import annotations

from dataclasses import dataclass

from app.metrics import MIN_MARKET_CAP as US_MIN_MARKET_CAP

# Yahoo returns marketCap for .HK equities in HKD in practice.
# Hard floor: HK$100億 = 100 × 1e8 = 10_000_000_000 (NOT 100e9 / 1000億).
HK_MIN_MARKET_CAP = 10_000_000_000
HK_MICRO_CAP = 1_000_000_000
HK_PENNY_PRICE = 0.5


@dataclass(frozen=True)
class MarketConfig:
    id: str
    title: str
    subtitle: str
    benchmark: str
    benchmark_label: str
    benchmark_short: str
    min_market_cap: float
    micro_cap: float
    penny_price: float
    cap_fail_label: str
    market_cap_currency: str
    money_unit: str
    market_cap_note: str
    rs_score_label: str
    equity_only_message: str
    apply_otc_gate: bool
    snapshot_key: str
    db_name: str
    universe_group: str


US_MARKET = MarketConfig(
    id="us",
    title="美股篩選器",
    subtitle="美股第二階段觀察台",
    benchmark="SPY",
    benchmark_label="標普500（SPY）",
    benchmark_short="SPY",
    min_market_cap=float(US_MIN_MARKET_CAP),
    micro_cap=300_000_000,
    penny_price=5.0,
    cap_fail_label="市值不足20億美元或未明",
    market_cap_currency="USD",
    money_unit="美元",
    market_cap_note="市值門檻 20 億美元（Yahoo marketCap，美元）。",
    rs_score_label="一星期相對 SPY",
    equity_only_message="這不是美股普通股",
    apply_otc_gate=True,
    snapshot_key="snapshot",
    db_name="market.sqlite",
    universe_group="us",
)

HK_MARKET = MarketConfig(
    id="hk",
    title="港股篩選器",
    subtitle="港股第二階段觀察台",
    benchmark="^HSI",
    benchmark_label="恆生指數（HSI）",
    benchmark_short="恆指",
    min_market_cap=float(HK_MIN_MARKET_CAP),
    micro_cap=float(HK_MICRO_CAP),
    penny_price=float(HK_PENNY_PRICE),
    cap_fail_label="市值不足100億港元或未明",
    market_cap_currency="HKD",
    money_unit="港元",
    market_cap_note=(
        "市值門檻 100 億港元（Yahoo marketCap，港元；1 億=1e8，故 100 億=1e10）。"
        "Yahoo 對 .HK 普通股的 marketCap 通常以港元計；本站按港元直接比較，不作即時匯率換算。"
    ),
    rs_score_label="一星期相對恆指",
    equity_only_message="這不是港股普通股",
    apply_otc_gate=False,
    snapshot_key="snapshot",
    db_name="market_hk.sqlite",
    universe_group="hk",
)


def get_market(market_id: str) -> MarketConfig:
    if market_id == "hk":
        return HK_MARKET
    if market_id == "us":
        return US_MARKET
    raise KeyError(market_id)
