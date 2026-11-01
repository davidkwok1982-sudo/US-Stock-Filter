import { useEffect, useRef } from "react"
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts"

import type { Bar, LinePoint, PriceLevel } from "@/lib/types.ts"

type RangeKey = "6m" | "1y" | "2y"

const UP = "#c4332b"
const DOWN = "#1c7a45"
const GOLD = "#e0b15a"
const BLUE = "#8eb4ea"

export function StockChart({
  bars,
  sma50,
  sma200,
  levels,
  range,
}: {
  bars: Bar[]
  sma50: LinePoint[]
  sma200: LinePoint[]
  levels: PriceLevel[]
  range: RangeKey
}) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = host.current
    if (!element || bars.length === 0) return
    const start = cutoff(range)
    const candles = bars.filter((bar) => bar.time >= start)
    if (candles.length === 0) return
    const first = candles[0]?.time ?? start

    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#141816" },
        textColor: "#d9d2c5",
        fontFamily: '"IBM Plex Mono", "Noto Sans TC", sans-serif',
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.045)" },
        horzLines: { color: "rgba(255,255,255,0.045)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.12)" },
      timeScale: { borderColor: "rgba(255,255,255,0.12)", fixLeftEdge: true, fixRightEdge: true },
    })

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: false,
    })
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.26 } })
    candle.setData(
      candles.map((bar) => ({
        time: bar.time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    )

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    })
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    volume.setData(
      candles.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(196,51,43,0.45)" : "rgba(28,122,69,0.45)",
      })),
    )

    const fast = chart.addSeries(LineSeries, {
      color: GOLD,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    fast.setData(sma50.filter((point) => point.time >= first).map((point) => ({ time: point.time, value: point.value })))

    const slow = chart.addSeries(LineSeries, {
      color: BLUE,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    slow.setData(sma200.filter((point) => point.time >= first).map((point) => ({ time: point.time, value: point.value })))

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

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars, levels, range, sma50, sma200])

  return <div ref={host} className="h-[420px] w-full sm:h-[540px]" />
}

function cutoff(range: RangeKey): string {
  const days = range === "6m" ? 190 : range === "1y" ? 372 : 760
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
}
