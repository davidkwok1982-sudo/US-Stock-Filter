import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { StockChart } from "@/components/stock-chart.tsx"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchStock } from "@/lib/api.ts"
import {
  betaCaption,
  formatBeta,
  formatPct,
  formatPrice,
  formatUsdLabeled,
  toneClass,
} from "@/lib/format.ts"
import { useScreen } from "@/lib/screen-context.tsx"
import type { ChartInterval, CompanyProfile, StockDetail } from "@/lib/types.ts"

type RangeKey = "6m" | "1y" | "2y" | "5d" | "10d" | "60d"

const INTERVALS: { key: ChartInterval; label: string }[] = [
  { key: "1d", label: "日線" },
  { key: "1wk", label: "週線" },
  { key: "1h", label: "小時" },
]

function defaultRange(interval: ChartInterval): RangeKey {
  return interval === "1h" ? "60d" : "1y"
}

function smaHint(interval: ChartInterval): string {
  if (interval === "1wk") return "金線 50週 · 綠線 150週 · 藍線 200週"
  if (interval === "1h") return "金線 50小時 · 綠線 150小時 · 藍線 200小時"
  return "金線 50天 · 綠線 150天 · 藍線 200天"
}

export function StockPage() {
  const { symbol = "" } = useParams()
  const [detail, setDetail] = useState<StockDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [chartInterval, setChartInterval] = useState<ChartInterval>("1d")
  const [range, setRange] = useState<RangeKey>("1y")
  const [summaryOpen, setSummaryOpen] = useState(false)

  useEffect(() => {
    const cleaned = symbol.trim().toUpperCase()
    if (!cleaned) return
    let stop = false
    setLoading(true)
    setError(null)
    setDetail(null)
    setSummaryOpen(false)
    fetchStock(cleaned, chartInterval)
      .then((next) => {
        if (stop) return
        setDetail(next)
        sessionStorage.setItem("kailut-symbol", next.row.symbol)
        document.title = `美股篩選器 · ${next.row.symbol}`
      })
      .catch((reason: unknown) => {
        if (!stop) setError(reason instanceof Error ? reason.message : "未能載入這隻股份")
      })
      .finally(() => {
        if (!stop) setLoading(false)
      })
    return () => {
      stop = true
    }
  }, [symbol, chartInterval])

  function selectInterval(next: ChartInterval) {
    setChartInterval(next)
    setRange(defaultRange(next))
  }

  if (!symbol) return <StockPicker />

  const row = detail?.row
  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/">返回篩選</Link>
      </Button>

      {loading ? (
        <div className="space-y-3" aria-live="polite">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-[420px] w-full" />
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-dashed border-border px-4 py-12 text-center">
          <p className="font-heading text-2xl">未能打開這隻股份</p>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          <Button asChild className="mt-4" variant="outline">
            <Link to="/stock">改看其他代號</Link>
          </Button>
        </div>
      ) : null}

      {row && detail ? (
        <>
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-heading text-4xl font-semibold">{row.symbol}</h1>
                {row.groupLabels.map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))}
                <Badge variant={row.passHard ? "default" : "secondary"}>{row.passHard ? "通過第二階段" : "未通過"}</Badge>
              </div>
              <p className="mt-1 text-muted-foreground">
                {row.name}
                {row.exchange ? ` · ${row.exchange}` : ""}
              </p>
            </div>
            <div className="text-right">
              <p className="num text-3xl">{formatPrice(row.price)}</p>
              <p className={`num ${toneClass(row.changePct)}`}>{formatPct(row.changePct, 2)}</p>
            </div>
          </header>

          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Fact label="市值" value={formatUsdLabeled(row.marketCap)} />
            <Fact label="日均成交額" value={formatUsdLabeled(row.dollarVolume)} />
            <Fact label="對200天" value={formatPct(row.vsSma200)} className={toneClass(row.vsSma200)} />
            <Fact label="貝他" value={`${formatBeta(row.beta)} ${betaCaption(row.betaBasis)}`.trim()} />
          </dl>

          <ul className="flex flex-wrap gap-2 text-sm">
            <Gate label="價＞50＞150＞200" ok={!row.failCodes.includes("ma_stack") && (row.maStacked ?? row.aboveSma200)} />
            <Gate label="均線向上" ok={!row.failCodes.includes("ma_slope") && row.slopeUp} />
            <Gate label="市值逾20億" ok={!row.failCodes.includes("cap")} />
            <Gate label="成交額" ok={!row.failCodes.includes("liquidity")} />
            <Gate label="貝他≥1" ok={!row.failCodes.includes("beta") && !row.failCodes.includes("beta_missing")} />
          </ul>
          {row.failReasons.length > 0 ? (
            <p className="text-sm text-muted-foreground">未過：{row.failReasons.join("、")}</p>
          ) : null}

          {detail.profile ? <CompanyProfileCard profile={detail.profile} summaryOpen={summaryOpen} onToggleSummary={() => setSummaryOpen((v) => !v)} /> : null}

          <section className="overflow-hidden rounded-xl bg-chart text-white">
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs text-[#d9d2c5]">
              <p>
                上方指數（SPY）陰陽燭 · 升紅跌綠 · {smaHint(chartInterval)} · 成交量 · 相對強度
                RS（近一星期對 SPY）· MACD 樣式
                {chartInterval === "1d" ? " · 虛線為支持／阻力" : ""}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex gap-1" role="group" aria-label="圖表週期">
                  {INTERVALS.map(({ key, label }) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => selectInterval(key)}
                      className={`rounded px-2.5 py-1 font-medium ${chartInterval === key ? "bg-white/20 text-white" : "text-white/70 hover:text-white"}`}
                      aria-pressed={chartInterval === key}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1" role="group" aria-label="顯示範圍">
                  {(chartInterval === "1h"
                    ? ([
                        ["5d", "5天"],
                        ["10d", "10天"],
                        ["60d", "約兩月"],
                      ] as const)
                    : ([
                        ["6m", "半年"],
                        ["1y", "一年"],
                        ["2y", "兩年"],
                      ] as const)
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setRange(key)}
                      className={`rounded px-2 py-1 ${range === key ? "bg-white/15 text-white" : "text-white/70"}`}
                      aria-pressed={range === key}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <StockChart
              bars={detail.bars}
              sma50={detail.sma50}
              sma150={detail.sma150 ?? []}
              sma200={detail.sma200}
              index={detail.index ?? null}
              levels={detail.levels}
              range={range}
              interval={chartInterval}
              symbol={row.symbol}
            />
          </section>

          {chartInterval === "1d" ? (
            detail.levels.length > 0 ? (
              <ul className="flex flex-wrap gap-2 text-sm">
                {detail.levels.map((level) => (
                  <li key={`${level.kind}-${level.price}`} className="rounded-md border border-border px-2 py-1">
                    <span className="text-muted-foreground">{level.label}</span>
                    <span className="num ml-2">{formatPrice(level.price)}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{level.touches} 次</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">近期擺動未夠密，未能標出可靠的支持或阻力。</p>
            )
          ) : (
            <p className="text-sm text-muted-foreground">支持／阻力僅在日線顯示；週線與小時圖顯示陰陽燭、均線、成交量與相對強度 RS（近一星期對 SPY）。資料點太少時會隱藏 RS 窗格。</p>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Card>
              <CardHeader>
                <CardTitle className="font-heading text-xl">優劣說明</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <p className="text-xs tracking-[0.16em] text-muted-foreground">技術</p>
                  <ul className="mt-2 space-y-2 text-sm leading-relaxed">
                    {detail.notes.technical.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
                <Separator />
                <div>
                  <p className="text-xs tracking-[0.16em] text-muted-foreground">基本</p>
                  <ul className="mt-2 space-y-2 text-sm leading-relaxed">
                    {detail.notes.fundamental.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
                <p className="border-t border-border pt-3 text-sm font-medium">{detail.notes.disclaimer}</p>
                <p className="text-xs leading-relaxed text-muted-foreground">{detail.notes.disclaimerLong}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="font-heading text-xl">評分 {row.score}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs leading-relaxed text-muted-foreground">滿分 100，只用於候選之間排序，不是買賣訊號。</p>
                {(row.scoreParts ?? []).map((part) => (
                  <div key={part.key}>
                    <div className="flex justify-between text-xs">
                      <span>{part.label}</span>
                      <span className="num">
                        {part.points}/{part.max}
                      </span>
                    </div>
                    <div className="mt-1 h-1 bg-secondary">
                      <div
                        className="h-full bg-brass"
                        style={{ width: `${part.max ? (part.points / part.max) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                ))}
                <Separator />
                <dl className="space-y-1 text-sm">
                  <Pair label="50天線" value={row.sma50 == null ? "—" : formatPrice(row.sma50)} />
                  <Pair label="150天線" value={row.sma150 == null ? "—" : formatPrice(row.sma150)} />
                  <Pair label="200天線" value={row.sma200 == null ? "—" : formatPrice(row.sma200)} />
                  <Pair label="一星期RS" value={formatPct(row.rs1w ?? null)} />
                  <Pair label="市盈率" value={row.pe == null ? "—" : `${row.pe.toFixed(1)} 倍`} />
                </dl>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}

export function StockPicker() {
  const { data } = useScreen()
  const [query, setQuery] = useState("")
  const rows = (data?.rows ?? []).filter((row) => row.passHard)
  const q = query.trim().toLowerCase()
  const matches = rows
    .filter((row) => !q || row.symbol.toLowerCase().includes(q) || row.name.toLowerCase().includes(q))
    .slice(0, 12)

  useEffect(() => {
    document.title = "美股篩選器 · 個股詳情"
  }, [])

  return (
    <div className="mx-auto max-w-lg py-8">
      <h1 className="font-heading text-3xl font-semibold">個股詳情</h1>
      <p className="mt-2 text-sm text-muted-foreground">從篩選結果選一隻股份，或輸入代號。圖表上方為 SPY 指數陰陽燭，中間為股價與50／150／200天線，下方為成交量，並標出近期擺動的支持與阻力。</p>
      <Input
        className="mt-5"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="例如 NVDA、Apple"
        aria-label="搜尋股份"
      />
      <ul className="mt-4 divide-y divide-border border-y border-border">
        {matches.map((row) => (
          <li key={row.symbol}>
            <Link
              to={`/stock/${row.symbol}`}
              className="flex items-baseline justify-between gap-3 py-3"
              onClick={() => sessionStorage.setItem("kailut-symbol", row.symbol)}
            >
              <span>
                <span className="font-medium">{row.symbol}</span>
                <span className="ml-2 text-sm text-muted-foreground">{row.name}</span>
              </span>
              <span className="num text-sm">{row.score}</span>
            </Link>
          </li>
        ))}
        {matches.length === 0 ? <li className="py-6 text-sm text-muted-foreground">沒有符合的通過股份。若快取仍在更新，請稍後再搜。</li> : null}
      </ul>
    </div>
  )
}


function CompanyProfileCard({
  profile,
  summaryOpen,
  onToggleSummary,
}: {
  profile: CompanyProfile
  summaryOpen: boolean
  onToggleSummary: () => void
}) {
  const sectorZh = profile.sectorZh ?? profile.sector
  const industryZh = profile.industryZh ?? profile.industry
  const sectorLine =
    sectorZh && profile.sectorEn && sectorZh !== profile.sectorEn
      ? `${sectorZh}（${profile.sectorEn}）`
      : sectorZh || profile.sectorEn || "—"
  const industryLine =
    industryZh && profile.industryEn && industryZh !== profile.industryEn
      ? `${industryZh}（${profile.industryEn}）`
      : industryZh || profile.industryEn || "—"
  const summary = profile.summary?.trim() || ""
  const longSummary = summary.length > 320
  const websiteHref = profile.website
    ? profile.website.startsWith("http")
      ? profile.website
      : `https://${profile.website}`
    : null
  const employees =
    profile.employees == null
      ? null
      : profile.employees.toLocaleString("zh-Hant")

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="font-heading text-xl">公司資料</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-relaxed">
        <dl className="grid gap-2 sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">板塊</dt>
            <dd className="mt-0.5">{sectorLine}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">行業</dt>
            <dd className="mt-0.5">{industryLine}</dd>
          </div>
          {employees ? (
            <div>
              <dt className="text-xs text-muted-foreground">員工數</dt>
              <dd className="mt-0.5 num">{employees}</dd>
            </div>
          ) : null}
          {profile.hq ? (
            <div>
              <dt className="text-xs text-muted-foreground">總部</dt>
              <dd className="mt-0.5">{profile.hq}</dd>
            </div>
          ) : null}
          {websiteHref ? (
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">官網</dt>
              <dd className="mt-0.5">
                <a
                  href={websiteHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brass underline-offset-2 hover:underline break-all"
                >
                  {profile.website}
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
        {summary ? (
          <div>
            <p className="text-xs tracking-[0.16em] text-muted-foreground">公司簡介</p>
            <p className={`mt-2 whitespace-pre-wrap ${summaryOpen || !longSummary ? "" : "line-clamp-6"}`}>
              {summary}
            </p>
            {longSummary ? (
              <button
                type="button"
                className="mt-2 text-xs font-medium text-brass hover:underline"
                onClick={onToggleSummary}
              >
                {summaryOpen ? "顯示較少" : "顯示更多"}
              </button>
            ) : null}
          </div>
        ) : (
          <p className="text-muted-foreground">暫無公司簡介。</p>
        )}
        <p className="border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
          資料來自 Yahoo Finance 公開接口，可能落後或不全。僅供參考，不構成投資建議。
        </p>
      </CardContent>
    </Card>
  )
}

function Fact({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`num mt-1 ${className}`}>{value}</dd>
    </div>
  )
}

function Gate({ label, ok }: { label: string; ok: boolean }) {
  return (
    <li className="rounded-md border border-border px-2 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-2 font-medium">{ok ? "通過" : "未過"}</span>
    </li>
  )
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  )
}
