"""Strategy registry.

Stage 2 is the only active screen. Trend-template and growth-stock slots are
named here so a later module can register `evaluate()` without changing the UI
contract. Their status stays `soon` until that work exists.
"""

from __future__ import annotations

STRATEGIES = [
    {
        "id": "jlaw-stage2",
        "name": "階律篩選",
        "status": "active",
        "summary": "第二階段條件：50＞150＞200、三條均線向上、市值逾20億美元。股票池為全美上市普通股（剔除 ADR 與 ETF）。",
    },
    {
        "id": "minervini",
        "name": "趨勢模板",
        "status": "soon",
        "summary": "即將推出。預留位置：股價高於150及200天線、150天線高於200天線、52週低位距離、相對強度排名等公開趨勢模板。",
    },
    {
        "id": "oneil",
        "name": "成長股法則",
        "status": "soon",
        "summary": "即將推出。預留位置：盈利與銷售增長、接近新高、領先股與需求等公開成長股篩選框架。",
    },
]


def get_strategy(strategy_id: str) -> dict | None:
    for strategy in STRATEGIES:
        if strategy["id"] == strategy_id:
            return strategy
    return None
