"""Short technical and fundamental notes. Observation, not advice."""

from __future__ import annotations

DISCLAIMER = "短線觀察，非投資建議。"
DISCLAIMER_LONG = (
    "短線觀察，非投資建議。本內容只按公開描述的第二階段條件作教育用途近似，"
    "並非任何專有交易系統，亦不構成招攬或買賣建議。"
)


def _px(value: float | None) -> str:
    if value is None:
        return "未明"
    if abs(value) >= 1:
        return f"US${value:,.2f}"
    return f"US${value:.4f}"


def _usd(value: float | None) -> str:
    if value is None:
        return "未明"
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1e12:
        return f"{sign}{amount / 1e12:.2f}萬億美元"
    if amount >= 1e8:
        scaled = amount / 1e8
        digits = 2 if scaled < 10 else 1 if scaled < 100 else 0
        return f"{sign}{scaled:.{digits}f}億美元"
    if amount >= 1e4:
        return f"{sign}{amount / 1e4:,.0f}萬美元"
    return f"{sign}{amount:,.0f}美元"


def _pct(value: float, digits: int = 1) -> str:
    return f"{abs(value) * 100:.{digits}f}%"


def _slope_phrase(name: str, slope: float | None) -> str:
    if slope is None:
        return ""
    verb = "上升" if slope > 0 else "回落" if slope < 0 else "走平"
    return f"{name}過去約一個月{verb} {_pct(slope)}。"


def build_notes(row: dict, levels: list[dict]) -> dict:
    technical: list[str] = []
    price = row.get("price")
    sma200 = row.get("sma200")
    sma50 = row.get("sma50")

    if price and sma200:
        distance = price / sma200 - 1
        slope = _slope_phrase("200天線", row.get("sma200Slope"))
        if distance > 0:
            technical.append(
                f"現價 {_px(price)}，高於200天線 {_pct(distance)}。{slope}長期均線仍在股價下方。"
            )
        else:
            technical.append(
                f"現價 {_px(price)}，低於200天線 {_pct(distance)}。{slope}尚未符合第二階段的長期條件。"
            )
    else:
        technical.append("日線不足以計算200天線，未能判斷是否處於第二階段。")

    if price and sma50:
        gap = price / sma50 - 1
        slope = _slope_phrase("50天線", row.get("sma50Slope"))
        if gap >= 0:
            technical.append(f"現價高於50天線 {_pct(gap)}。{slope}中期結構仍在50天線之上。")
        else:
            technical.append(f"現價低於50天線 {_pct(gap)}，短線轉弱。{slope}須留意會否繼續靠攏200天線。")

    high_bits: list[str] = []
    high_52 = row.get("high52")
    if price and high_52:
        drawdown = price / high_52 - 1
        if drawdown >= -0.001:
            high_bits.append(f"股價貼近階段高位（{_px(high_52)}）")
        elif drawdown >= -0.25:
            high_bits.append(f"距52週高位 {_pct(drawdown)}（高位 {_px(high_52)}），仍在25%觀察範圍內")
        else:
            high_bits.append(f"較52週高位回落 {_pct(drawdown)}（高位 {_px(high_52)}），並未貼近高位")
        if (row.get("barsCount") or 0) < 252:
            high_bits.append("現有日線不足一年，高位只覆蓋已下載數據")
    rs1w = row.get("rs1w")
    if rs1w is not None:
        if rs1w >= 0:
            high_bits.append(f"近一星期回報較 SPY 高出 {rs1w * 100:.1f} 個百分點")
        else:
            high_bits.append(f"近一星期回報落後 SPY {abs(rs1w) * 100:.1f} 個百分點，相對強度偏弱")
    if high_bits:
        technical.append("，".join(high_bits) + "。")

    flow: list[str] = []
    dollar = row.get("dollarVolume")
    if dollar:
        window = "近63個交易日" if row.get("dollarVolumeBasis") == "63d" else "以三個月平均成交量估算，"
        if dollar >= 100_000_000:
            quality = "流動性充足"
        elif dollar >= 30_000_000:
            quality = "高於3,000萬美元的每日成交額門檻"
        else:
            quality = "未達3,000萬美元的每日成交額門檻"
        prefix = window if row.get("dollarVolumeBasis") == "63d" else "按報價估算，"
        flow.append(f"{prefix}平均每日成交額約 {_usd(dollar)}，{quality}")
    beta = row.get("beta")
    if beta is not None and row.get("betaBasis") == "yahoo":
        flow.append(f"貝他 {beta:.2f}（Yahoo Finance 公布值）")
    elif beta is not None:
        flow.append(f"90日貝他 {beta:.2f}（相對 SPY；Yahoo 未提供貝他）")
    else:
        flow.append("貝他未能估算")
    supports = [level for level in levels if level["kind"] == "support"]
    resistance = [level for level in levels if level["kind"] == "resistance"]
    if supports:
        nearest = supports[0]
        flow.append(f"下方較近{nearest['label']}約 {_px(nearest['price'])}")
    if resistance:
        nearest = resistance[0]
        flow.append(f"上方較近{nearest['label']}約 {_px(nearest['price'])}")
    if flow:
        technical.append("。".join(flow) + "。")

    fundamental: list[str] = []
    sector = row.get("sector")
    industry = row.get("industry")
    pe = row.get("pe")
    if sector:
        line = f"行業屬{sector}"
        if industry and industry != sector:
            line += f"，細分{industry}"
        line += "。"
        if pe:
            line += f"過去十二個月市盈率約 {pe:.1f} 倍。"
        else:
            line += "暫無可用市盈率。"
        fundamental.append(line)
    elif pe:
        fundamental.append(f"過去十二個月市盈率約 {pe:.1f} 倍。行業資料暫缺。")

    growth_bits: list[str] = []
    revenue = row.get("revenueGrowth")
    earnings = row.get("earningsGrowth")
    if revenue is not None:
        if revenue >= 0:
            growth_bits.append(f"收入按年增長約 {revenue * 100:.1f}%")
        else:
            growth_bits.append(f"收入按年收縮約 {abs(revenue) * 100:.1f}%")
    if earnings is not None:
        if earnings >= 0:
            growth_bits.append(f"盈利按年增長約 {earnings * 100:.1f}%")
        else:
            growth_bits.append(f"盈利按年收縮約 {abs(earnings) * 100:.1f}%")
    if growth_bits:
        fundamental.append("，".join(growth_bits) + "。數字來自 Yahoo Finance 免費來源，可能落後於最新季報。")
    elif fundamental:
        fundamental.append("免費來源暫未提供收入增長。")
    else:
        fundamental.append("免費來源暫未提供行業或收入增長。")

    return {
        "technical": technical[:4],
        "fundamental": fundamental[:2],
        "disclaimer": DISCLAIMER,
        "disclaimerLong": DISCLAIMER_LONG,
    }
