import { useEffect, useRef } from "react"
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts"

import type { Bar, IndexSeries, LinePoint, PriceLevel } from "@/lib/types.ts"

type RangeKey = "6m" | "1y" | "2y"

const UP = "#c4332b"
const DOWN = "#1c7a45"
const GOLD = "#e0b15a"
const BLUE = "#8eb4ea"
const INDEX = "#c4a1ff"

export function StockChart({
  bars,
  sma50,
  sma200,
  index,
  levels,
  range,
}: {
  bars: Bar[]
  sma50: LinePoint[]
  sma200: LinePoint[]
  index: IndexSeries | null
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
    const firstClose = candles[0]?.close
    if (firstClose == null || firstClose <= 0) return

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
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } })
    candle.setData(
      candles.map((bar) => ({
        time: bar.time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
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

    const rebased = rebaseIndex(index, first, firstClose)
    if (rebased.length > 0) {
      const benchmark = chart.addSeries(LineSeries, {
        color: INDEX,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        title: index?.symbol ?? "SPY",
        crosshairMarkerVisible: false,
      })
      benchmark.setData(rebased)
    }

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
      1,
    )
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } })
    volume.setData(
      candles.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(196,51,43,0.55)" : "rgba(28,122,69,0.55)",
      })),
    )

    const panes = chart.panes()
    if (panes.length > 1) {
      panes[0]?.setHeight(Math.max(280, Math.floor(element.clientHeight * 0.72)))
      panes[1]?.setHeight(Math.max(90, Math.floor(element.clientHeight * 0.28)))
    }

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars, index, levels, range, sma50, sma200])

  return <div ref={host} className="h-[480px] w-full sm:h-[620px]" />
}

function cutoff(range: RangeKey): string {
  const days = range === "6m" ? 190 : range === "1y" ? 372 : 760
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
}

/** Rebase index closes onto the stock's first visible close so outperformance is visible. */
function rebaseIndex(index: IndexSeries | null, firstTime: string, firstClose: number) {
  const closes = (index?.closes ?? []).filter((point) => point.time >= firstTime && point.value > 0)
  if (closes.length === 0) return []
  const base = closes[0]?.value
  if (base == null || base <= 0) return []
  return closes.map((point) => ({
    time: point.time,
    value: Number(((firstClose * point.value) / base).toFixed(4)),
  }))
}
