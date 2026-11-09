import { useEffect, useMemo, useState } from "react"
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

const DEFAULT_GAIN1W = 5

export function ScreenPage() {
  const { data, loadError, refresh, copy, market, refreshing } = useScreen()
  useEffect(() => {
    document.title = `${copy.title} · 篩選結果`
  }, [copy.title])
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => readFilters(params), [params])

  function update(next: Filters) {
    setParams(writeFilters(next), { replace: true })
  }

  function toggle(key: "rs" | "support") {
    update({ ...filters, [key]: !filters[key] })
  }

  const [gainDraft, setGainDraft] = useState<string | null>(null)
  const gainActive = filters.gain1w != null
  const gainInput = gainDraft ?? (gainActive ? String(filters.gain1w) : "")

  useEffect(() => {
    if (filters.gain1w == null) setGainDraft(null)
  }, [filters.gain1w])

  function toggleGain1w() {
    if (filters.gain1w != null) {
      setGainDraft(null)
      update({ ...filters, gain1w: null })
      return
    }
    setGainDraft(String(DEFAULT_GAIN1W))
    update({ ...filters, gain1w: DEFAULT_GAIN1W })
  }

  function onGain1wChange(raw: string) {
    setGainDraft(raw)
    const trimmed = raw.trim()
    if (trimmed === "" || trimmed === "-" || trimmed === "." || trimmed === "-.") return
    const n = Number(trimmed)
    if (!Number.isFinite(n)) return
    update({ ...filters, gain1w: n })
  }

  function onGain1wBlur() {
    if (filters.gain1w == null) {
      setGainDraft(null)
      return
    }
    setGainDraft(String(filters.gain1w))
  }

  function onSort(key: SortKey) {
    if (filters.sort === key) {
      update({ ...filters, dir: filters.dir === "asc" ? "desc" : "asc" })
      return
    }
    update({ ...filters, sort: key, dir: key === "symbol" || key === "name" ? "asc" : "desc" })
  }

  const ready = Boolean(data?.ready && data.meta?.universe && data.meta?.summary)
  const coldHint = !ready && !refreshing && Boolean(data && !data.refresh.running)
  const rows = useMemo(() => (data?.rows ? visibleRows(data.rows, filters) : []), [data, filters])
  const passCount = data?.meta?.summary?.pass ?? 0
  const leaders = useMemo(() => {
    if (!data?.rows) return []
    return data.rows.filter((row) => row.passHard).slice(0, 5)
  }, [data])

  const toggles: { key: "rs" | "support"; label: string; hint: string }[] = [
    { key: "rs", label: copy.rsChip, hint: copy.rsHint },
    {
      key: "support",
      label: "收市近支持",
      hint: "最新收市價落在結構支持區內（清晰擺動低點＋近20／60日區間低點，須≥2次觸及；區間為中軸±0.5×ATR）。與圖表支持位同一套定義",
    },
  ]

  return (
    <div className="min-w-0 space-y-6">
      {!ready && !loadError && !coldHint ? (
        <LoadingState
          message={data?.refresh.message ?? "正在連線"}
          progress={data?.refresh.progress ?? 4}
          market={market}
        />
      ) : null}
      {coldHint ? (
        <ColdStartState
          title={copy.title}
          hint={data?.meta?.hint ?? (market === "hk"
            ? "港股快取尚未建立。Hobby 部署為臨時磁碟，請先按「重新整理」建立股票池。"
            : "美股快取尚未建立。請按「重新整理」建立股票池。")}
          onRefresh={() => void refresh()}
          refreshing={refreshing}
        />
      ) : null}
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

      {ready && data?.meta?.universe && data.meta.summary ? (
        <>
          <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
            <div>
              <p className="text-xs tracking-[0.16em] text-muted-foreground">第二階段通過</p>
              <p className="font-heading text-5xl leading-none font-semibold">
                {passCount}
                <span className="ml-2 text-lg font-normal text-muted-foreground">隻</span>
              </p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              {copy.universeBlurb(data.meta.universe.unique, data.meta.universe.evaluated)}
              {copy.benchmarkShort} 近一星期 {formatPct(data.meta.spy?.ret1w ?? data.meta.spy?.ret6m ?? null)}。
            </p>
            <dl className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-3">
              <Stat label="未符合股價＞50＞150＞200" value={data.meta.summary.failMaStack ?? data.meta.summary.failSma200} />
              <Stat label="均線未全部向上" value={data.meta.summary.failMaSlope ?? 0} />
              <Stat label="市值不足或未明" value={data.meta.summary.failCap} />
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">以上為未通過硬性條件的家數；同一股份可計入多於一項。硬性條件通過與否，不受下面的可選收緊影響。</p>
          </section>

          {leaders.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">評分較高</span>
              {leaders.map((row) => (
                <Button key={row.symbol} asChild variant="outline" size="sm">
                  <Link
                    to={copy.stockPath(row.symbol)}
                    onClick={() => sessionStorage.setItem(copy.sessionKey, row.symbol)}
                  >
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
            <div className="flex flex-wrap items-center gap-2">
              {toggles.map((item) => {
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
              <div
                className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 ${
                  filters.gain1w != null ? "border-transparent bg-primary text-primary-foreground" : "border-border bg-background"
                }`}
                title={`近約 5 個交易日（一星期）收市對收市升幅；只計股份本身，唔係相對 ${copy.benchmarkShort}。可輸入門檻百分比。`}
              >
                <Button
                  type="button"
                  size="sm"
                  variant={filters.gain1w != null ? "default" : "outline"}
                  className="h-7 border-0 shadow-none"
                  aria-pressed={filters.gain1w != null}
                  onClick={toggleGain1w}
                >
                  近一星期升幅
                </Button>
                {filters.gain1w != null ? (
                  <>
                    <span className="text-xs opacity-80">&gt;</span>
                    <Input
                      type="number"
                      inputMode="decimal"
                      step="0.5"
                      value={gainInput}
                      onChange={(event) => onGain1wChange(event.target.value)}
                      onBlur={onGain1wBlur}
                      onClick={(event) => event.stopPropagation()}
                      aria-label="近一星期升幅門檻百分比"
                      className="h-7 w-16 border-0 bg-background/20 px-1.5 text-center text-sm text-inherit shadow-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    <span className="pr-1 text-xs opacity-80">%</span>
                  </>
                ) : null}
              </div>
            </div>
            <details className="text-sm text-muted-foreground">
              <summary className="cursor-pointer text-foreground">怎樣讀這張表</summary>
              <p className="mt-2 max-w-3xl leading-relaxed">
                預設只列出通過篩選的股份：現價＞50天線＞150天線＞200天線、三條均線過去約一星期都向上、{copy.hardCapBlurb}。評分把距離均線、斜率、近一星期相對 {copy.benchmarkShort} 和流動性加總，方便排序。可選按鈕會再收緊名單，但不會改寫上面的通過家數。「{copy.rsChip}」須近約 5 個與 20 個交易日收市對收市總回報減 {copy.benchmarkShort} 皆為正。「收市近支持」以結構支持區（擺動＋近20／60日低點、≥2次觸及、±0.5×ATR）判斷；最新收市須落在該區內。「近一星期升幅」要求股份本身近約 5 個交易日收市對收市升幅達到你輸入的門檻（預設 5%），唔係相對 {copy.benchmarkShort}。
                <Link to={`${copy.basePath}/strategy`} className="ml-2 text-foreground underline underline-offset-4">
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
                    rs: false,
                    support: false,
                    gain1w: null,
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

function LoadingState({ message, progress, market }: { message: string; progress: number; market: string }) {
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
        {market === "hk"
          ? "首次會按批次向 Yahoo Finance 下載港交所普通股日線，並以恆生指數作相對強度基準；需時較長，並寫入本機快取。"
          : "首次會按批次向 Yahoo Finance 下載全美普通股日線（已剔除 ADR／ETF），需時較長，並寫入本機快取；更新中可先看已完成部分。"}
      </p>
    </div>
  )
}

function ColdStartState({
  title,
  hint,
  onRefresh,
  refreshing,
}: {
  title: string
  hint: string
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-heading text-2xl">{title}</p>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{hint}</p>
      <Button type="button" className="mt-6" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? "更新中…" : "重新整理股票池"}
      </Button>
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
