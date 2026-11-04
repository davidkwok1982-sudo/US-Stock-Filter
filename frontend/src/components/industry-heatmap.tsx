import { useMemo, type CSSProperties } from "react"
import { useNavigate } from "react-router-dom"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatPct, toneClass } from "@/lib/format.ts"
import { cn } from "@/lib/utils.ts"
import type { ScreenRow } from "@/lib/types.ts"

const UNLABELED = "未分類"

type IndustryBucket = {
  key: string
  label: string
  count: number
  rank: number
  rows: ScreenRow[]
}

function industryKey(row: ScreenRow): string {
  const industry = row.industry?.trim()
  if (industry) return industry
  const sector = row.sector?.trim()
  if (sector) return sector
  return UNLABELED
}

function shortName(name: string | null | undefined, max = 10): string {
  const value = (name ?? "").trim()
  if (!value) return ""
  return value.length > max ? `${value.slice(0, max)}…` : value
}

function boardLabel(row: ScreenRow): string {
  const sector = row.sector?.trim() || UNLABELED
  const industry = row.industry?.trim()
  if (industry && industry !== sector) return `${sector} · ${industry}`
  return sector
}

function groupByIndustry(rows: ScreenRow[]): IndustryBucket[] {
  const map = new Map<string, ScreenRow[]>()
  for (const row of rows) {
    const key = industryKey(row)
    const list = map.get(key)
    if (list) list.push(row)
    else map.set(key, [row])
  }
  const buckets = Array.from(map.entries()).map(([key, items]) => ({
    key,
    label: key,
    count: items.length,
    rank: 0,
    rows: [...items].sort((a, b) => b.score - a.score || a.symbol.localeCompare(b.symbol)),
  }))
  buckets.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "zh-Hant"))
  return buckets.map((bucket, index) => ({ ...bucket, rank: index + 1 }))
}

/** Hotter background for higher-count industries (rank-aware). */
function blockStyle(rank: number, count: number, maxCount: number): CSSProperties {
  const intensity = maxCount <= 1 ? 1 : count / maxCount
  // Warm brass → primary red heat scale matching site palette
  if (rank === 1) {
    return {
      background: `linear-gradient(145deg, rgba(157,44,36,${0.22 + intensity * 0.28}) 0%, rgba(196,165,116,${0.35 + intensity * 0.25}) 100%)`,
      borderColor: "rgba(157, 44, 36, 0.55)",
    }
  }
  if (rank === 2) {
    return {
      background: `linear-gradient(145deg, rgba(157,44,36,${0.14 + intensity * 0.22}) 0%, rgba(196,165,116,${0.28 + intensity * 0.2}) 100%)`,
      borderColor: "rgba(138, 98, 50, 0.5)",
    }
  }
  if (rank === 3) {
    return {
      background: `linear-gradient(145deg, rgba(138,98,50,${0.12 + intensity * 0.2}) 0%, rgba(196,165,116,${0.22 + intensity * 0.18}) 100%)`,
      borderColor: "rgba(138, 98, 50, 0.4)",
    }
  }
  const alpha = 0.06 + intensity * 0.18
  return {
    background: `rgba(196, 165, 116, ${alpha})`,
    borderColor: "rgba(216, 208, 194, 0.9)",
  }
}

function tileShade(score: number, maxScore: number): string {
  if (maxScore <= 0) return "bg-card/70"
  const t = Math.max(0, Math.min(1, score / maxScore))
  if (t >= 0.75) return "bg-card/95 border-primary/35"
  if (t >= 0.5) return "bg-card/85 border-brass/30"
  return "bg-card/70 border-border/80"
}

function openRow(navigate: ReturnType<typeof useNavigate>, symbol: string) {
  sessionStorage.setItem("kailut-symbol", symbol)
  void navigate(`/stock/${symbol}`)
}

export function IndustryHeatmap({ rows }: { rows: ScreenRow[] }) {
  const buckets = useMemo(() => groupByIndustry(rows), [rows])
  const maxCount = buckets[0]?.count ?? 0
  const navigate = useNavigate()

  if (rows.length === 0 || buckets.length === 0) return null

  const leaders = buckets.slice(0, 3)
  const rest = buckets.slice(3)

  return (
    <section
      className="rounded-xl border border-border bg-card p-4 sm:p-5"
      aria-labelledby="industry-heatmap-title"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs tracking-[0.16em] text-muted-foreground">領導版塊</p>
          <h2 id="industry-heatmap-title" className="font-heading text-2xl font-semibold">
            細分版塊熱力圖
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            第二階段名單按細分版塊家數排名，先看領導版塊，再在版塊內找評分／相對強度較高的股份。每隻股顯示所屬版塊。
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          {buckets.length} 個細分版塊 · {rows.length} 隻
        </p>
      </div>

      {/* Hero: #1 full-width, #2/#3 side-by-side */}
      {leaders[0] ? (
        <div className="mt-5">
          <IndustryBlock
            bucket={leaders[0]}
            maxCount={maxCount}
            hero
            onOpen={(symbol) => openRow(navigate, symbol)}
          />
        </div>
      ) : null}
      {leaders.length > 1 ? (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {leaders.slice(1).map((bucket) => (
            <IndustryBlock
              key={bucket.key}
              bucket={bucket}
              maxCount={maxCount}
              hero
              onOpen={(symbol) => openRow(navigate, symbol)}
            />
          ))}
        </div>
      ) : null}

      {rest.length > 0 ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {rest.map((bucket) => (
            <IndustryBlock
              key={bucket.key}
              bucket={bucket}
              maxCount={maxCount}
              hero={false}
              onOpen={(symbol) => openRow(navigate, symbol)}
            />
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: "rgba(157,44,36,0.55)" }} />
          家數較多（熱）
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: "rgba(196,165,116,0.28)" }} />
          家數較少
        </span>
        <span>排名依第二階段篩選後家數；版塊內按評分排序，並顯示六個月 RS。</span>
      </div>
    </section>
  )
}

function IndustryBlock({
  bucket,
  maxCount,
  hero,
  onOpen,
}: {
  bucket: IndustryBucket
  maxCount: number
  hero: boolean
  onOpen: (symbol: string) => void
}) {
  const maxScore = bucket.rows.reduce((m, r) => Math.max(m, r.score), 0)
  const isTop = bucket.rank <= 3

  return (
    <article
      className={cn(
        "rounded-lg border p-3 transition-shadow",
        hero && bucket.rank === 1 && "shadow-md ring-1 ring-primary/25 lg:col-span-1",
        hero && "min-h-[11rem]",
      )}
      style={blockStyle(bucket.rank, bucket.count, maxCount)}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "num inline-flex items-center justify-center rounded-md px-1.5 py-0.5 text-xs font-medium",
                bucket.rank === 1 && "bg-primary text-primary-foreground",
                bucket.rank === 2 && "bg-brass text-primary-foreground",
                bucket.rank === 3 && "bg-brass-soft text-ink",
                bucket.rank > 3 && "bg-secondary text-foreground",
              )}
            >
              #{bucket.rank}
            </span>
            <h3
              className={cn(
                "truncate font-heading font-semibold",
                isTop ? "text-lg sm:text-xl" : "text-base",
              )}
              title={bucket.label}
            >
              {bucket.label}
            </h3>
          </div>
        </div>
        <p className={cn("num shrink-0 font-medium", isTop ? "text-2xl" : "text-lg")}>
          {bucket.count}
          <span className="ml-1 text-xs font-normal text-muted-foreground">隻</span>
        </p>
      </header>

      <ul
        className={cn(
          "mt-3 flex flex-wrap gap-1.5",
          hero && bucket.rank === 1 && "gap-2",
        )}
      >
        {bucket.rows.map((row) => {
          const board = boardLabel(row)
          const name = shortName(row.name)
          return (
            <li key={row.symbol}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => onOpen(row.symbol)}
                    className={cn(
                      "rounded-md border px-2 py-1 text-left transition-colors hover:border-primary/50 hover:bg-card",
                      hero && bucket.rank <= 2 ? "min-w-[5.25rem]" : "min-w-[4.5rem]",
                      tileShade(row.score, maxScore),
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className={cn("font-medium", hero ? "text-sm" : "text-xs")}>
                        {row.symbol}
                      </span>
                      <span className="num text-[10px] text-muted-foreground" title="評分">
                        {row.score}
                      </span>
                    </div>
                    {name ? (
                      <span className="block max-w-[7.5rem] truncate text-[10px] text-muted-foreground">
                        {name}
                      </span>
                    ) : null}
                    <span className="mt-0.5 block max-w-[7.5rem] truncate text-[10px] leading-tight text-brass">
                      {board}
                    </span>
                    <span
                      className={cn(
                        "num mt-0.5 block text-[10px]",
                        toneClass(row.rs6m),
                        row.rsBeat ? "font-medium" : "",
                      )}
                      title="六個月相對 SPY"
                    >
                      RS {formatPct(row.rs6m)}
                    </span>
                  </button>
                </TooltipTrigger>
                <TooltipContent className="flex-col items-start gap-0.5 py-2">
                  <span className="font-medium">
                    {row.symbol}
                    {row.name ? ` · ${row.name}` : ""}
                  </span>
                  <span>版塊：{board}</span>
                  <span className="text-background/80">評分 {row.score} · 六個月 RS {formatPct(row.rs6m)}</span>
                  {row.rsBeat ? <span className="text-background/80">跑贏 SPY</span> : null}
                </TooltipContent>
              </Tooltip>
            </li>
          )
        })}
      </ul>
    </article>
  )
}
