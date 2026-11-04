import { useEffect, useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"

import { IndustryHeatmap } from "@/components/industry-heatmap.tsx"
import { ScreenTable } from "@/components/screen-table.tsx"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { readFilters, visibleRows, writeFilters } from "@/lib/filters.ts"
import { formatPct } from "@/lib/format.ts"
import { useScreen } from "@/lib/screen-context.tsx"
import type { Filters, SortKey } from "@/lib/types.ts"

const TOGGLES: { key: keyof Filters; label: string; hint: string }[] = [
  { key: "above50", label: "高於50天線", hint: "現價高於50天線" },
  { key: "slope", label: "均線向上", hint: "50／150／200天線過去約一個月都向上（硬性條件已要求；此鈕可再強調）" },
  { key: "rs", label: "跑贏 SPY", hint: "近一星期回報高於 SPY（約5個交易日）" },
  { key: "support", label: "收市近支持", hint: "最新收市價剛好落在近期擺動支持位附近（約 ±1%），允許輕微刺穿但未明顯跌破（教育約數）" },
  { key: "excludeMicro", label: "排除場外及微盤", hint: "剔除股價低於 5 美元、市值少於 3 億或場外代號" },
]

export function ScreenPage() {
  const { data, loadError, refresh } = useScreen()
  useEffect(() => {
    document.title = "美股篩選器 · 篩選結果"
  }, [])
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => readFilters(params), [params])

  function update(next: Filters) {
    setParams(writeFilters(next), { replace: true })
  }

  function toggle(key: keyof Filters) {
    update({ ...filters, [key]: !filters[key] })
  }

  function onSort(key: SortKey) {
    if (filters.sort === key) {
      update({ ...filters, dir: filters.dir === "asc" ? "desc" : "asc" })
      return
    }
    update({ ...filters, sort: key, dir: key === "symbol" || key === "name" ? "asc" : "desc" })
  }

  const ready = Boolean(data?.ready && data.meta)
  const rows = useMemo(() => (data?.rows ? visibleRows(data.rows, filters) : []), [data, filters])
  const passCount = data?.meta?.summary.pass ?? 0
  const leaders = useMemo(() => {
    if (!data?.rows) return []
    return data.rows.filter((row) => row.passHard).slice(0, 5)
  }, [data])

  return (
    <div className="space-y-6">
      {!ready && !loadError ? <LoadingState message={data?.refresh.message ?? "正在連線"} progress={data?.refresh.progress ?? 4} /> : null}
      {loadError && !ready ? (
        <ErrorState message={loadError} onRetry={() => void refresh()} />
      ) : null}
      {data?.refresh.error && ready ? (
        <p className="rounded-md border border-border bg-card px-3 py-2 text-sm">{data.refresh.error}</p>
      ) : null}
      {ready && data?.refresh.running ? (
        <p className="text-sm text-muted-foreground" aria-live="polite">
          正在背景更新：{data.refresh.message}（{data.refresh.progress}%）。現在顯示的仍是上一份快取。
        </p>
      ) : null}

      {ready && data?.meta ? (
        <>
          <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs tracking-[0.16em] text-muted-foreground">第二階段通過</p>
                <p className="font-heading text-5xl leading-none font-semibold">
                  {passCount}
                  <span className="ml-2 text-lg font-normal text-muted-foreground">隻</span>
                </p>
              </div>
              <p className={`max-w-sm text-sm ${breadthClass(data.meta.breadth.tone)}`}>{data.meta.breadth.label}</p>
            </div>
            <BreadthMeter count={passCount} />
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              家數只計本宇宙（標普500 {data.meta.universe.sp500}、標普中型400 {data.meta.universe.sp400}、納指100 {data.meta.universe.ndx}，合併 {data.meta.universe.unique} 隻），不是全市場。200／100 沿用公開文章的經驗數字，只作觀察。
              SPY 近一星期 {formatPct(data.meta.spy.ret1w ?? data.meta.spy.ret6m)}。
            </p>
            <dl className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-5">
              <Stat label="未呈價＞50＞150＞200" value={data.meta.summary.failMaStack ?? data.meta.summary.failSma200} />
              <Stat label="均線未全部向上" value={data.meta.summary.failMaSlope ?? 0} />
              <Stat label="市值不足或未明" value={data.meta.summary.failCap} />
              <Stat label="成交額不足" value={data.meta.summary.failLiquidity} />
              <Stat label="貝他不足或未明" value={data.meta.summary.failBeta} />
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">同一股份可計入多於一項。硬性條件通過與否，不受下面的可選收緊影響。</p>
          </section>

          {leaders.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">評分較高</span>
              {leaders.map((row) => (
                <Button key={row.symbol} asChild variant="outline" size="sm">
                  <Link to={`/stock/${row.symbol}`} onClick={() => sessionStorage.setItem("kailut-symbol", row.symbol)}>
                    {row.symbol}
                    <span className="num text-muted-foreground">{row.score}</span>
                  </Link>
                </Button>
              ))}
            </div>
          ) : null}

          <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Input
                value={filters.q}
                onChange={(event) => update({ ...filters, q: event.target.value })}
                placeholder="搜尋代號或名稱"
                aria-label="搜尋代號或名稱"
                className="sm:max-w-xs"
              />
              <p className="text-sm text-muted-foreground">顯示 {rows.length} 隻 · 通過家數 {passCount}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {TOGGLES.map((item) => {
                const on = Boolean(filters[item.key])
                return (
                  <Button
                    key={item.key}
                    type="button"
                    size="sm"
                    variant={on ? "default" : "outline"}
                    aria-pressed={on}
                    title={item.hint}
                    onClick={() => toggle(item.key)}
                  >
                    {item.label}
                  </Button>
                )
              })}
            </div>
            <details className="text-sm text-muted-foreground">
              <summary className="cursor-pointer text-foreground">怎樣讀這張表</summary>
              <p className="mt-2 max-w-3xl leading-relaxed">
                預設只列出通過硬性條件的股份：現價＞50天線＞150天線＞200天線、三條均線過去約一個月都向上、市值逾20億美元、日均成交額約3,000萬美元、貝他不低於1。評分把距離均線、斜率、近一星期相對 SPY 和流動性加總，方便排序，不是買賣訊號。可選按鈕會再收緊名單，但不會改寫上面的通過家數。「收市近支持」以日線擺動低點估計支持；最新收市落在該位約 ±1% 內（可輕微刺穿、明顯跌破則否），屬教育約數。
                <Link to="/strategy" className="ml-2 text-foreground underline underline-offset-4">
                  策略說明
                </Link>
              </p>
            </details>
          </div>

          {rows.length > 0 ? <IndustryHeatmap rows={rows} /> : null}

          {rows.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border px-4 py-12 text-center">
              <p className="font-heading text-xl">沒有股份同時符合目前條件</p>
              <p className="mt-2 text-sm text-muted-foreground">可放寬可選收緊，或待下一次行情更新。</p>
              <Button
                type="button"
                className="mt-4"
                variant="outline"
                onClick={() =>
                  update({
                    ...filters,
                    q: "",
                    above50: false,
                    slope: false,
                    nearHigh: false,
                    rs: false,
                    support: false,
                    excludeMicro: true,
                  })
                }
              >
                放寬可選條件
              </Button>
            </div>
          ) : (
            <ScreenTable rows={rows} sort={filters.sort} dir={filters.dir} onSort={onSort} />
          )}
        </>
      ) : null}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border pt-2">
      <dt>{label}</dt>
      <dd className="num text-sm text-foreground">{value}</dd>
    </div>
  )
}

function BreadthMeter({ count }: { count: number }) {
  const marker = Math.max(0, Math.min(100, (count / 300) * 100))
  return (
    <div className="mt-5">
      <div className="relative h-2 bg-secondary">
        <div className="absolute inset-y-0 left-0 w-1/3 bg-[#cfc3ae]" />
        <div className="absolute inset-y-0 left-1/3 w-1/3 bg-[#b08958]" />
        <div className="absolute inset-y-0 left-2/3 right-0 bg-brass" />
        <div
          className="absolute top-1/2 size-3 -translate-y-1/2 rounded-full border border-background bg-foreground"
          style={{ left: `calc(${marker}% - 6px)` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
        <span>0 審慎</span>
        <span>100</span>
        <span>200 偏多</span>
        <span>300</span>
      </div>
    </div>
  )
}

function breadthClass(tone: "bullish" | "neutral" | "cautious"): string {
  if (tone === "bullish") return "text-up"
  if (tone === "cautious") return "text-down"
  return "text-brass"
}

function LoadingState({ message, progress }: { message: string; progress: number }) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center" aria-live="polite">
      <p className="font-heading text-2xl">正在整理第二階段名單</p>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      <div className="mt-6 h-1 bg-secondary">
        <div className="h-full bg-up transition-[width]" style={{ width: `${Math.max(4, Math.min(100, progress))}%` }} />
      </div>
      <p className="num mt-3 text-xs text-muted-foreground">{progress}%</p>
      <div className="mt-8 space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-4/5" />
      </div>
      <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
        首次會向 Yahoo Finance 下載標普500、標普中型400及納指100的日線，大約需要半分鐘，並寫入本機快取。
      </p>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-heading text-2xl">暫時未能取得行情</p>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      <Button type="button" className="mt-4" onClick={onRetry}>
        再試一次
      </Button>
    </div>
  )
}
