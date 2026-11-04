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

type RangeKey = "6m" | "1y" | "2y" | "5d" | "10d" | "60d"

const UP = "#c4332b"
const DOWN = "#1c7a45"
const GOLD = "#e0b15a"
const BLUE = "#8eb4ea"
const RS_MACD = "#e0b15a"
const RS_SIGNAL = "#8eb4ea"
/** Need ~26 for slow EMA + ~9 for signal before MACD is usable. */
const RS_MIN_ALIGNED = 35

export function StockChart({
  bars,
  sma50,
  sma200,
  index,
  levels,
  range,
  interval = "1d",
  symbol,
}: {
  bars: Bar[]
  sma50: LinePoint[]
  sma200: LinePoint[]
  index: IndexSeries | null
  levels: PriceLevel[]
  range: RangeKey
  interval?: ChartInterval
  symbol?: string
}) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = host.current
    if (!element || bars.length === 0) return
    const start = cutoff(range, interval)
    const candles = bars.filter((bar) => timeAtOrAfter(bar.time, start))
    if (candles.length === 0) return
    const first = candles[0]?.time ?? start

    const indexBars = indexCandles(index, first)
    // Use full history for EMA warmup, then plot from visible range.
    const indexAll = indexCandles(index, bars[0]?.time ?? first)
    const rsMacd = computeRsMacd(bars, indexAll.length > 0 ? indexAll : indexBars).filter((point) =>
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
      rightPriceScale: { borderColor: "rgba(255,255,255,0.12)" },
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
      ...(symbol ? { title: symbol } : {}),
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

    const fast = stockPane.addSeries(LineSeries, {
      color: GOLD,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    fast.setData(
      sma50
        .filter((point) => timeAtOrAfter(point.time, first))
        .map((point) => ({ time: toChartTime(point.time), value: point.value })),
    )

    const slow = stockPane.addSeries(LineSeries, {
      color: BLUE,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    slow.setData(
      sma200
        .filter((point) => timeAtOrAfter(point.time, first))
        .map((point) => ({ time: toChartTime(point.time), value: point.value })),
    )

    for (const level of levels) {
      candle.createPriceLine({
        price: level.price,
        color: level.kind === "support" ? GOLD : BLUE,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.label,
      })
    }

    const volumePane = chart.addPane(false)
    const volume = volumePane.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
      title: "成交量",
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
        title: "RS",
        priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
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
        priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
      })
      macdLine.setData(rsMacd.map((point) => ({ time: toChartTime(point.time), value: point.macd })))

      const signalLine = rsPane.addSeries(LineSeries, {
        color: RS_SIGNAL,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
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
        title: index?.symbol ?? "SPY",
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
  }, [bars, index, interval, levels, range, sma50, sma200, symbol])

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

function cutoff(range: RangeKey, interval: ChartInterval): ChartTime {
  const now = Date.now()
  if (interval === "1h") {
    const hours = range === "5d" ? 5 * 24 : range === "10d" ? 10 * 24 : 60 * 24
    return Math.floor(now / 1000) - hours * 3600
  }
  const days = range === "6m" ? 190 : range === "1y" ? 372 : 760
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
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

/** RS = stockClose / spyClose; MACD(12,26,9) on that ratio. Empty if too few aligned bars. */
function computeRsMacd(stockBars: Bar[], spyBars: Bar[]): RsMacdPoint[] {
  if (stockBars.length === 0 || spyBars.length === 0) return []

  const spyClose = new Map<string, number>()
  for (const bar of spyBars) {
    if (bar.close > 0) spyClose.set(timeKey(bar.time), bar.close)
  }

  const rsValues: number[] = []
  const rsTimes: ChartTime[] = []
  for (const bar of stockBars) {
    if (bar.close <= 0) continue
    const spy = spyClose.get(timeKey(bar.time))
    if (spy == null || spy <= 0) continue
    rsValues.push(bar.close / spy)
    rsTimes.push(bar.time)
  }

  if (rsValues.length < RS_MIN_ALIGNED) return []

  const ema12 = emaSeries(rsValues, 12)
  const ema26 = emaSeries(rsValues, 26)

  const macdValues: number[] = []
  const macdTimes: ChartTime[] = []
  for (let i = 0; i < rsValues.length; i++) {
    const fast = ema12[i]
    const slow = ema26[i]
    if (fast == null || slow == null) continue
    macdValues.push(fast - slow)
    macdTimes.push(rsTimes[i]!)
  }

  if (macdValues.length < 9) return []

  const signal = emaSeries(macdValues, 9)
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
