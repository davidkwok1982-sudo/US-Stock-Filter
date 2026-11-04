import { useEffect, useRef } from "react"
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type Time,
} from "lightweight-charts"

import type { Bar, ChartInterval, ChartTime, IndexSeries, LinePoint, PriceLevel } from "@/lib/types.ts"

const UP = "#c4332b"
const DOWN = "#1c7a45"
const SILVER = "#c9c4b8"
const ORANGE = "#d4896a"
const GOLD = "#e0b15a"
const BLUE = "#8eb4ea"
const MA_LINE_WIDTH = 1 as const
const RS_MACD = "#e0b15a"
const RS_SIGNAL = "#8eb4ea"
/** Short MACD(5,13,5) on 1w RS needs lookback + ~18 points. */
const RS_MIN_POINTS = 20
const RS_MACD_FAST = 5
const RS_MACD_SLOW = 13
const RS_MACD_SIGNAL = 5

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

  useEffect(() => {
    const element = host.current
    if (!element || bars.length === 0) return
    // Fit all loaded bars; free zoom remains via chart interaction.
    const candles = bars
    const first = candles[0]!.time

    const indexBars = indexCandles(index, first)
    // Use full history for EMA warmup, then plot from visible range.
    const indexAll = indexCandles(index, bars[0]?.time ?? first)
    const rsMacd = computeRsMacd(bars, indexAll.length > 0 ? indexAll : indexBars, interval).filter((point) =>
      timeAtOrAfter(point.time, first),
    )
    const showRs = rsMacd.length > 0

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
        color: bar.close >= bar.open ? "rgba(196,51,43,0.55)" : "rgba(28,122,69,0.55)",
      })),
    )

    // RS pane sits under volume (before SPY is created/moved).
    let rsPane = null as ReturnType<typeof chart.addPane> | null
    if (showRs) {
      rsPane = chart.addPane(false)
      const hist = rsPane.addSeries(HistogramSeries, {
        priceLineVisible: false,
        lastValueVisible: false,
        title: "",
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      })
      hist.priceScale().applyOptions({ scaleMargins: { top: 0.12, bottom: 0.08 } })
      hist.setData(
        rsMacd.map((point) => ({
          time: toChartTime(point.time),
          value: point.hist,
          color: point.hist >= 0 ? "rgba(196,51,43,0.65)" : "rgba(28,122,69,0.65)",
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

      const macdLine = rsPane.addSeries(LineSeries, {
        color: RS_MACD,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      })
      macdLine.setData(rsMacd.map((point) => ({ time: toChartTime(point.time), value: point.macd })))

      const signalLine = rsPane.addSeries(LineSeries, {
        color: RS_SIGNAL,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      })
      signalLine.setData(rsMacd.map((point) => ({ time: toChartTime(point.time), value: point.signal })))
    }

    let spyPane = null as ReturnType<typeof chart.addPane> | null
    if (indexBars.length > 0) {
      spyPane = chart.addPane(false)
      const spy = spyPane.addSeries(CandlestickSeries, {
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
      spy.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.1 } })
      spy.setData(
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

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars, index, interval, levels, sma10, sma20, sma50, sma150, sma200])

  return <div ref={host} className="h-[520px] w-full sm:h-[680px]" />
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

type RsMacdPoint = { time: ChartTime; macd: number; signal: number; hist: number }

/**
 * ~1-week relative strength vs SPY, then short MACD for display.
 *
 * Lookback by interval: 1d→5 bars, 1wk→1 bar, 1h→33 hourly bars (~1 trading week).
 * rs1w = stockReturn(lookback) - spyReturn(lookback); scaled ×100 (percentage points).
 * MACD(5,13,5) on that series. Above ~0 ≈ 近一星期強於／偏強於大盤.
 */
function computeRsMacd(stockBars: Bar[], spyBars: Bar[], interval: ChartInterval): RsMacdPoint[] {
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

  const lookback = rsLookbackBars(interval)
  if (alignedTimes.length < lookback + RS_MIN_POINTS) return []

  const rs1w: number[] = []
  const rsTimes: ChartTime[] = []
  for (let i = lookback; i < alignedTimes.length; i++) {
    const stockPrev = stockCloses[i - lookback]!
    const spyPrev = spyCloses[i - lookback]!
    if (stockPrev <= 0 || spyPrev <= 0) continue
    const stockRet = stockCloses[i]! / stockPrev - 1
    const spyRet = spyCloses[i]! / spyPrev - 1
    // Percentage points so the pane scale stays readable.
    rs1w.push((stockRet - spyRet) * 100)
    rsTimes.push(alignedTimes[i]!)
  }

  if (rs1w.length < RS_MIN_POINTS) return []

  const emaFast = emaSeries(rs1w, RS_MACD_FAST)
  const emaSlow = emaSeries(rs1w, RS_MACD_SLOW)

  const macdValues: number[] = []
  const macdTimes: ChartTime[] = []
  for (let i = 0; i < rs1w.length; i++) {
    const fast = emaFast[i]
    const slow = emaSlow[i]
    if (fast == null || slow == null) continue
    macdValues.push(fast - slow)
    macdTimes.push(rsTimes[i]!)
  }

  if (macdValues.length < RS_MACD_SIGNAL) return []

  const signal = emaSeries(macdValues, RS_MACD_SIGNAL)
  const out: RsMacdPoint[] = []
  for (let i = 0; i < macdValues.length; i++) {
    const sig = signal[i]
    if (sig == null) continue
    const macd = macdValues[i]!
    out.push({
      time: macdTimes[i]!,
      macd,
      signal: sig,
      hist: macd - sig,
    })
  }
  return out
}

/** Trading bars that approximate one week for each chart interval. */
function rsLookbackBars(interval: ChartInterval): number {
  if (interval === "1wk") return 1
  if (interval === "1h") return 33 // ~6.5 sessions × ~5 RTH hours
  return 5 // 1d: five trading days
}

function emaSeries(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = Array.from({ length: values.length }, () => null)
  if (values.length < period || period <= 0) return out
  const k = 2 / (period + 1)
  let sum = 0
  for (let i = 0; i < period; i++) sum += values[i]!
  let prev = sum / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = values[i]! * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}
