"""Strategy registry.

J Law Stage 2 is the only active screen. Minervini and O'Neil are named
here so a later module can register `evaluate()` without changing the UI
contract. Their status stays `soon` until that work exists.
"""

from __future__ import annotations

STRATEGIES = [
    {
        "id": "jlaw-stage2",
        "name": "J Law 第二階段",
        "status": "active",
        "summary": "以公開描述的 Stan Weinstein 第二階段條件做教育近似：股價高於200天線、市值逾20億美元、日均成交額約3,000萬美元、貝他不低於1。",
    },
    {
        "id": "minervini",
        "name": "Minervini 趨勢模板",
        "status": "soon",
        "summary": "即將推出。預留位置：股價高於150及200天線、150天線高於200天線、52週低位距離、相對強度排名等公開趨勢模板。",
    },
    {
        "id": "oneil",
        "name": "O'Neil CAN SLIM",
        "status": "soon",
        "summary": "即將推出。預留位置：盈利與銷售增長、接近新高、領先股與需求等公開 CAN SLIM 框架。",
    },
]


def get_strategy(strategy_id: str) -> dict | None:
    for strategy in STRATEGIES:
        if strategy["id"] == strategy_id:
            return strategy
    return None
