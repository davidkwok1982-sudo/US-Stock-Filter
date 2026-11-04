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

export function StockChart({
  bars,
  sma50,
  sma200,
  index,
  levels,
  range,
  interval = "1d",
}: {
  bars: Bar[]
  sma50: LinePoint[]
  sma200: LinePoint[]
  index: IndexSeries | null
  levels: PriceLevel[]
  range: RangeKey
  interval?: ChartInterval
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

    let stockPane = 0
    let volumePane = 1

    if (indexBars.length > 0) {
      const spy = chart.addSeries(CandlestickSeries, {
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
      chart.addPane(true)
      stockPane = 1
      volumePane = 2
    }

    const candle = chart.addSeries(
      CandlestickSeries,
      {
        upColor: UP,
        downColor: DOWN,
        borderUpColor: UP,
        borderDownColor: DOWN,
        wickUpColor: UP,
        wickDownColor: DOWN,
        priceLineVisible: false,
      },
      stockPane,
    )
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

    const fast = chart.addSeries(
      LineSeries,
      {
        color: GOLD,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      },
      stockPane,
    )
    fast.setData(
      sma50
        .filter((point) => timeAtOrAfter(point.time, first))
        .map((point) => ({ time: toChartTime(point.time), value: point.value })),
    )

    const slow = chart.addSeries(
      LineSeries,
      {
        color: BLUE,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      },
      stockPane,
    )
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

    chart.addPane(true)
    const volume = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
        title: "成交量",
      },
      volumePane,
    )
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } })
    volume.setData(
      candles.map((bar) => ({
        time: toChartTime(bar.time),
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(196,51,43,0.55)" : "rgba(28,122,69,0.55)",
      })),
    )

    const panes = chart.panes()
    const height = element.clientHeight
    if (panes.length >= 3) {
      panes[0]?.setHeight(Math.max(110, Math.floor(height * 0.22)))
      panes[1]?.setHeight(Math.max(240, Math.floor(height * 0.55)))
      panes[2]?.setHeight(Math.max(80, Math.floor(height * 0.23)))
    } else if (panes.length > 1) {
      panes[0]?.setHeight(Math.max(280, Math.floor(height * 0.72)))
      panes[1]?.setHeight(Math.max(90, Math.floor(height * 0.28)))
    }

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars, index, interval, levels, range, sma50, sma200])

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
