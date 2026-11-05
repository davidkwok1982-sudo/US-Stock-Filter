import { useEffect, useRef } from "react"
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createTextWatermark,
  type MouseEventParams,
  type Time,
} from "lightweight-charts"

import type { Bar, ChartInterval, ChartTime, IndexSeries, LinePoint, PriceLevel } from "@/lib/types.ts"

const UP = "#1c7a45"
const DOWN = "#c4332b"
const SILVER = "#c9c4b8"
const ORANGE = "#d4896a"
const GOLD = "#e0b15a"
const BLUE = "#8eb4ea"
const MA_LINE_WIDTH = 1 as const
/** Same-bar excess return % vs SPY: (stockRet − spyRet)×100. */
const RS_BAR_PERIOD = 1

export function StockChart({
  bars,
  sma10 = [],
  sma20 = [],
  sma50,
  sma150 = [],
  sma200,
  index,
  levels,
  interval = "1d",
}: {
  bars: Bar[]
  sma10?: LinePoint[]
  sma20?: LinePoint[]
  sma50: LinePoint[]
  sma150?: LinePoint[]
  sma200: LinePoint[]
  index: IndexSeries | null
  levels: PriceLevel[]
  interval?: ChartInterval
  symbol?: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = host.current
    const tooltipEl = tooltipRef.current
    if (!element || bars.length === 0) return
    // Load full series; initial viewport is a sliced window (zoom/pan can reveal the rest).
    const candles = bars
    const first = candles[0]!.time

    const indexBars = indexCandles(index, first)
    // Align SPY from full stock history so early excess points are available.
    const indexAll = indexCandles(index, bars[0]?.time ?? first)
    const rsPoints = computeRsExcess(bars, indexAll.length > 0 ? indexAll : indexBars).filter((point) =>
      timeAtOrAfter(point.time, first),
    )
    const showRs = rsPoints.length > 0

    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#141816" },
        textColor: "#d9d2c5",
        fontFamily: '"IBM Plex Mono", "Noto Sans TC", sans-serif',
        panes: {
          separatorColor: "rgba(255,255,255,0.12)",
          separatorHoverColor: "rgba(255,255,255,0.22)",
        },
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.045)" },
        horzLines: { color: "rgba(255,255,255,0.045)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.12)",
        minimumWidth: 72,
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.12)",
        fixLeftEdge: true,
        fixRightEdge: true,
        timeVisible: interval === "1h",
        secondsVisible: false,
      },
    })

    // Stock owns the default pane first so it cannot be swallowed if a later
    // index pane fails or collapses. SPY is added last and moved above.
    const stockPane = chart.panes()[0]
    if (!stockPane) {
      chart.remove()
      return
    }

    const candle = stockPane.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: false,
      // Keep symbol off the pane; page legend already names it. Price on right axis.
      title: "",
      lastValueVisible: true,
    })
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } })
    candle.setData(
      candles.map((bar) => ({
        time: toChartTime(bar.time),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    )

    const plotMa = (series: LinePoint[], color: string) => {
      const line = stockPane.addSeries(LineSeries, {
        color,
        lineWidth: MA_LINE_WIDTH,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      line.setData(
        series
          .filter((point) => timeAtOrAfter(point.time, first))
          .map((point) => ({ time: toChartTime(point.time), value: point.value })),
      )
    }
    plotMa(sma10, SILVER)
    plotMa(sma20, ORANGE)
    plotMa(sma50, GOLD)
    plotMa(sma150, "#9ec5b0")
    plotMa(sma200, BLUE)

    for (const level of levels) {
      const base = level.kind === "support" ? GOLD : BLUE
      // Mid-line only on chart (ATR lo–hi still used for detection/filter + level list).
      candle.createPriceLine({
        price: level.price,
        color: base,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        // Labels live in the level list under the chart; titles cover candles.
        axisLabelVisible: false,
        title: "",
      })
    }

    const volumePane = chart.addPane(false)
    const volume = volumePane.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
      title: "",
    })
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } })
    volume.setData(
      candles.map((bar) => ({
        time: toChartTime(bar.time),
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(28,122,69,0.55)" : "rgba(196,51,43,0.55)",
      })),
    )

    // RS pane under volume: one histogram = same-bar excess % vs SPY; zero = flat vs SPY.
    let rsPane = null as ReturnType<typeof chart.addPane> | null
    if (showRs) {
      rsPane = chart.addPane(false)
      const hist = rsPane.addSeries(HistogramSeries, {
        priceLineVisible: false,
        lastValueVisible: true,
        title: "",
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      })
      hist.priceScale().applyOptions({ scaleMargins: { top: 0.12, bottom: 0.08 } })
      hist.setData(
        rsPoints.map((point) => ({
          time: toChartTime(point.time),
          value: point.value,
          color: point.value >= 0 ? "rgba(28,122,69,0.65)" : "rgba(196,51,43,0.65)",
        })),
      )
      hist.createPriceLine({
        price: 0,
        color: "rgba(255,255,255,0.35)",
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: false,
        title: "",
      })
    }

    let spyPane = null as ReturnType<typeof chart.addPane> | null
    let spySeries: typeof candle | null = null
    if (indexBars.length > 0) {
      spyPane = chart.addPane(false)
      spySeries = spyPane.addSeries(CandlestickSeries, {
        upColor: UP,
        downColor: DOWN,
        borderUpColor: UP,
        borderDownColor: DOWN,
        wickUpColor: UP,
        wickDownColor: DOWN,
        priceLineVisible: false,
        title: "",
        lastValueVisible: true,
      })
      spySeries.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } })
      spySeries.setData(
        indexBars.map((bar) => ({
          time: toChartTime(bar.time),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })),
      )
      // Place SPY above the stock pane without making it the primary series at create time.
      spyPane.moveTo(0)
    }

    // Relative sizes: SPY ~18%, stock ~42%, volume ~18%, RS ~22% when all present.
    const panes = chart.panes()
    if (spyPane && rsPane && panes.length >= 4) {
      panes[0]?.setStretchFactor(0.18)
      panes[1]?.setStretchFactor(0.42)
      panes[2]?.setStretchFactor(0.18)
      panes[3]?.setStretchFactor(0.22)
    } else if (spyPane && panes.length >= 3) {
      panes[0]?.setStretchFactor(0.22)
      panes[1]?.setStretchFactor(0.55)
      panes[2]?.setStretchFactor(0.23)
    } else if (rsPane && panes.length >= 3) {
      panes[0]?.setStretchFactor(0.55)
      panes[1]?.setStretchFactor(0.22)
      panes[2]?.setStretchFactor(0.23)
    } else if (panes.length >= 2) {
      panes[0]?.setStretchFactor(0.72)
      panes[1]?.setStretchFactor(0.28)
    }

    // Discreet top-left pane titles (native LWC text watermarks; no tooltip impact).
    labelPane(spyPane, "SPY")
    labelPane(stockPane, "股價")
    labelPane(volumePane, "成交量")
    labelPane(rsPane, "RS")

    applyDefaultVisibleRange(chart, candles, interval)

    // OHLC + change% popup: stock pane → stock; SPY pane → SPY; hide on volume/RS.
    const barByTime = new Map<string, { bar: Bar; prevClose: number | null }>()
    for (let i = 0; i < candles.length; i++) {
      const bar = candles[i]!
      const prev = i > 0 ? candles[i - 1]!.close : null
      barByTime.set(timeKey(bar.time), { bar, prevClose: prev })
    }
    const spyByTime = new Map<string, { bar: Bar; prevClose: number | null }>()
    for (let i = 0; i < indexBars.length; i++) {
      const bar = indexBars[i]!
      const prev = i > 0 ? indexBars[i - 1]!.close : null
      spyByTime.set(timeKey(bar.time), { bar, prevClose: prev })
    }

    const stockPaneIndex = candle.getPane().paneIndex()
    const spyPaneIndex = spySeries ? spySeries.getPane().paneIndex() : -1

    const hideTooltip = () => {
      if (!tooltipEl) return
      tooltipEl.style.display = "none"
    }

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      if (!tooltipEl) return
      if (
        param.point === undefined ||
        param.time === undefined ||
        param.point.x < 0 ||
        param.point.y < 0 ||
        param.paneIndex === undefined
      ) {
        hideTooltip()
        return
      }

      const onStock = param.paneIndex === stockPaneIndex
      const onSpy = spySeries != null && param.paneIndex === spyPaneIndex
      // Volume / RS (and any other non-candle pane): no tooltip.
      if (!onStock && !onSpy) {
        hideTooltip()
        return
      }

      const series = onSpy && spySeries ? spySeries : candle
      const lookup = onSpy ? spyByTime : barByTime
      const title = onSpy ? "SPY" : null
      const raw = param.seriesData.get(series)
      if (
        !raw ||
        !("open" in raw) ||
        !("high" in raw) ||
        !("low" in raw) ||
        !("close" in raw) ||
        raw.open == null ||
        raw.high == null ||
        raw.low == null ||
        raw.close == null
      ) {
        hideTooltip()
        return
      }

      const open = raw.open
      const high = raw.high
      const low = raw.low
      const close = raw.close
      const barTime = ("time" in raw && raw.time != null ? raw.time : param.time) as ChartTime
      const keyed = lookup.get(timeKey(barTime))
      const prevClose = keyed?.prevClose ?? null
      const changePct =
        prevClose != null && prevClose > 0 ? ((close - prevClose) / prevClose) * 100 : null
      const up = changePct == null ? close >= open : changePct >= 0
      const changeColor = up ? UP : DOWN
      const changeText =
        changePct == null
          ? "—"
          : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`

      const row = (label: string, value: string, color?: string) =>
        `<div style="display:flex;justify-content:space-between;gap:12px">` +
        `<span style="color:#a39e93">${label}</span>` +
        `<span${color ? ` style="color:${color}"` : ""}>${value}</span></div>`

      const timeLabel = formatTooltipTime(barTime, interval)
      const header = title
        ? `<div style="margin-bottom:2px;font-size:10px;letter-spacing:0.06em;color:#d9d2c5;font-weight:600">${title}</div>` +
          `<div style="margin-bottom:4px;padding-bottom:4px;border-bottom:1px solid rgba(255,255,255,0.1);font-size:10px;letter-spacing:0.04em;color:#a39e93">${timeLabel}</div>`
        : `<div style="margin-bottom:4px;padding-bottom:4px;border-bottom:1px solid rgba(255,255,255,0.1);font-size:10px;letter-spacing:0.04em;color:#a39e93">${timeLabel}</div>`
      tooltipEl.innerHTML =
        header +
        row("開 Open", fmtPrice(open)) +
        row("高 High", fmtPrice(high)) +
        row("低 Low", fmtPrice(low)) +
        row("收 Close", fmtPrice(close), changeColor) +
        `<div style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,0.1);display:flex;justify-content:space-between;gap:12px">` +
        `<span style="color:#a39e93">升跌%</span>` +
        `<span style="color:${changeColor};font-weight:600">${changeText}</span></div>`

      tooltipEl.style.display = "block"
      const width = tooltipEl.offsetWidth || 148
      const height = tooltipEl.offsetHeight || 120
      const hostWidth = element.clientWidth
      const hostHeight = element.clientHeight
      let left = param.point.x + 16
      let top = param.point.y + 16
      if (left + width > hostWidth - 8) left = param.point.x - width - 16
      if (top + height > hostHeight - 8) top = param.point.y - height - 16
      if (left < 8) left = 8
      if (top < 8) top = 8

      tooltipEl.style.left = `${left}px`
      tooltipEl.style.top = `${top}px`
    }

    chart.subscribeCrosshairMove(onCrosshairMove)

    return () => {
      chart.unsubscribeCrosshairMove(onCrosshairMove)
      chart.remove()
    }
  }, [bars, index, interval, levels, sma10, sma20, sma50, sma150, sma200])

  return (
    <div className="relative h-[520px] w-full sm:h-[680px]">
      <div ref={host} className="h-full w-full" />
      <div
        ref={tooltipRef}
        className="pointer-events-none absolute z-20 hidden min-w-[148px] rounded-md border border-white/15 bg-[#1a1f1c]/95 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-[#d9d2c5] shadow-lg backdrop-blur-sm"
      />
    </div>
  )
}


/** Initial viewport by timeframe; full series stays loaded for zoom-out/pan.
 * 日線 ~6 months (近6個月), 週線 ~1 year, 小時 ~1 week.
 */
function defaultVisibleCutoff(interval: ChartInterval): ChartTime {
  const now = Date.now()
  if (interval === "1h") {
    return Math.floor(now / 1000) - 7 * 24 * 3600
  }
  const days = interval === "1wk" ? 372 : 186
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
}


function labelPane(
  pane: ReturnType<ReturnType<typeof createChart>["addPane"]> | null | undefined,
  text: string,
): void {
  if (!pane) return
  createTextWatermark(pane, {
    visible: true,
    horzAlign: "left",
    vertAlign: "top",
    lines: [
      {
        text,
        color: "rgba(217, 210, 197, 0.42)",
        fontSize: 11,
        lineHeight: 14,
        fontFamily: '"IBM Plex Mono", "Noto Sans TC", sans-serif',
        fontStyle: "600",
      },
    ],
  })
}

function applyDefaultVisibleRange(
  chart: ReturnType<typeof createChart>,
  candles: Bar[],
  interval: ChartInterval,
): void {
  const last = candles[candles.length - 1]
  if (!last) {
    chart.timeScale().fitContent()
    return
  }
  const cutoff = defaultVisibleCutoff(interval)
  const from = timeAtOrAfter(cutoff, candles[0]!.time) ? cutoff : candles[0]!.time
  try {
    chart.timeScale().setVisibleRange({
      from: toChartTime(from),
      to: toChartTime(last.time),
    })
  } catch {
    chart.timeScale().fitContent()
  }
}


function fmtPrice(value: number): string {
  if (!Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  const digits = abs >= 1000 ? 2 : abs >= 100 ? 2 : abs >= 1 ? 2 : 4
  return value.toFixed(digits)
}

function formatTooltipTime(time: ChartTime, interval: ChartInterval): string {
  if (typeof time === "number") {
    const d = new Date(time * 1000)
    const y = d.getUTCFullYear()
    const m = String(d.getUTCMonth() + 1).padStart(2, "0")
    const day = String(d.getUTCDate()).padStart(2, "0")
    if (interval === "1h") {
      const hh = String(d.getUTCHours()).padStart(2, "0")
      const mm = String(d.getUTCMinutes()).padStart(2, "0")
      return `${y}-${m}-${day} ${hh}:${mm}`
    }
    return `${y}-${m}-${day}`
  }
  if (interval === "1h" && time.length > 10) return time.replace("T", " ").slice(0, 16)
  return time.slice(0, 10)
}

function toChartTime(time: ChartTime): Time {
  if (typeof time === "number") return time as Time
  return time as Time
}

function timeAtOrAfter(time: ChartTime, start: ChartTime): boolean {
  if (typeof time === "number" || typeof start === "number") {
    return toUnix(time) >= toUnix(start)
  }
  return time >= start
}

function toUnix(time: ChartTime): number {
  if (typeof time === "number") return time
  if (time.length <= 10) return Math.floor(new Date(`${time}T00:00:00Z`).getTime() / 1000)
  return Math.floor(new Date(time).getTime() / 1000)
}

function timeKey(time: ChartTime): string {
  return typeof time === "number" ? String(time) : time
}

/** Prefer API OHLC bars; fall back to close-only synthetic candles for older payloads. */
function indexCandles(index: IndexSeries | null, firstTime: ChartTime): Bar[] {
  if (!index) return []
  const bars = (index.bars ?? []).filter((bar) => timeAtOrAfter(bar.time, firstTime))
  if (bars.length > 0) return bars
  return (index.closes ?? [])
    .filter((point) => timeAtOrAfter(point.time, firstTime) && point.value > 0)
    .map((point) => ({
      time: point.time,
      open: point.value,
      high: point.value,
      low: point.value,
      close: point.value,
      volume: 0,
    }))
}

type RsExcessPoint = { time: ChartTime; value: number }

/**
 * Same-bar excess return % vs SPY on the current chart timeframe.
 *
 * value = (stockBarReturn − spyBarReturn)×100 for each aligned bar
 * Positive = beat SPY that bar; negative = lag. Soft filter 跑贏 SPY requires both 5d and 20d excess
 * stay on daily multi-day close-to-close excess (unchanged).
 */
function computeRsExcess(stockBars: Bar[], spyBars: Bar[]): RsExcessPoint[] {
  if (stockBars.length === 0 || spyBars.length === 0) return []

  const spyClose = new Map<string, number>()
  for (const bar of spyBars) {
    if (bar.close > 0) spyClose.set(timeKey(bar.time), bar.close)
  }

  const alignedTimes: ChartTime[] = []
  const stockCloses: number[] = []
  const spyCloses: number[] = []
  for (const bar of stockBars) {
    if (bar.close <= 0) continue
    const spy = spyClose.get(timeKey(bar.time))
    if (spy == null || spy <= 0) continue
    alignedTimes.push(bar.time)
    stockCloses.push(bar.close)
    spyCloses.push(spy)
  }

  if (alignedTimes.length <= RS_BAR_PERIOD) return []

  const out: RsExcessPoint[] = []
  for (let i = RS_BAR_PERIOD; i < alignedTimes.length; i++) {
    const value = excessPct(stockCloses, spyCloses, i, RS_BAR_PERIOD)
    if (value == null) continue
    out.push({ time: alignedTimes[i]!, value })
  }
  return out
}

function excessPct(
  stockCloses: number[],
  spyCloses: number[],
  index: number,
  period: number,
): number | null {
  if (index < period) return null
  const stockPrev = stockCloses[index - period]!
  const spyPrev = spyCloses[index - period]!
  if (stockPrev <= 0 || spyPrev <= 0) return null
  const stockRet = stockCloses[index]! / stockPrev - 1
  const spyRet = spyCloses[index]! / spyPrev - 1
  return (stockRet - spyRet) * 100
}
