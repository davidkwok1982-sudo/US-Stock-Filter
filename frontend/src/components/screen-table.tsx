import { useNavigate } from "react-router-dom"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import {
  betaCaption,
  formatBeta,
  formatPct,
  formatPrice,
  formatUsdLabeled,
  toneClass,
} from "@/lib/format.ts"
import type { ScreenRow, SortKey } from "@/lib/types.ts"

const COLUMNS: { key: SortKey; label: string; tip: string; align: "left" | "right" }[] = [
  { key: "symbol", label: "代號", tip: "美股代號", align: "left" },
  { key: "name", label: "名稱", tip: "公司名稱", align: "left" },
  { key: "price", label: "現價", tip: "最近報價，美元", align: "right" },
  { key: "changePct", label: "升跌", tip: "較上一個收市", align: "right" },
  { key: "marketCap", label: "市值", tip: "美元市值", align: "right" },
  { key: "dollarVolume", label: "日均成交額", tip: "近63日或三個月估算", align: "right" },
  { key: "vsSma200", label: "對200天", tip: "現價相對200天線", align: "right" },
  { key: "beta", label: "貝他", tip: "Yahoo 公布值，否則為90日對 SPY", align: "right" },
  { key: "rs6m", label: "六個月RS", tip: "六個月回報減 SPY", align: "right" },
  { key: "score", label: "評分", tip: "0至100，只用於排序", align: "right" },
]

export function ScreenTable({
  rows,
  sort,
  dir,
  onSort,
}: {
  rows: ScreenRow[]
  sort: SortKey
  dir: "asc" | "desc"
  onSort: (key: SortKey) => void
}) {
  const navigate = useNavigate()
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {COLUMNS.map((column) => (
                <TableHead key={column.key} className={column.align === "right" ? "text-right" : "text-left"}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={`inline-flex items-center gap-1 text-xs tracking-wide ${column.align === "right" ? "ml-auto" : ""}`}
                        onClick={() => onSort(column.key)}
                        aria-sort={sort === column.key ? (dir === "asc" ? "ascending" : "descending") : "none"}
                      >
                        {column.label}
                        <span className="text-[10px] text-muted-foreground">{sort === column.key ? (dir === "asc" ? "↑" : "↓") : ""}</span>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>{column.tip}</TooltipContent>
                  </Tooltip>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.symbol}
                className="cursor-pointer"
                tabIndex={0}
                onClick={() => openRow(navigate, row.symbol)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    openRow(navigate, row.symbol)
                  }
                }}
              >
                <TableCell className="font-medium">{row.symbol}</TableCell>
                <TableCell className="max-w-48 truncate text-muted-foreground">{row.name}</TableCell>
                <TableCell className="num text-right">{formatPrice(row.price)}</TableCell>
                <TableCell className={`num text-right ${toneClass(row.changePct)}`}>{formatPct(row.changePct, 2)}</TableCell>
                <TableCell className="num text-right">{formatUsdLabeled(row.marketCap)}</TableCell>
                <TableCell className="num text-right">{formatUsdLabeled(row.dollarVolume)}</TableCell>
                <TableCell className={`num text-right ${toneClass(row.vsSma200)}`}>{formatPct(row.vsSma200)}</TableCell>
                <TableCell className="num text-right">
                  {formatBeta(row.beta)}
                  <span className="ml-1 text-[10px] text-muted-foreground">{betaCaption(row.betaBasis)}</span>
                </TableCell>
                <TableCell className={`num text-right ${toneClass(row.rs6m)}`}>{formatPct(row.rs6m)}</TableCell>
                <TableCell className="text-right">
                  <ScoreMark score={row.score} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="grid gap-3 md:hidden">
        {rows.map((row) => (
          <li key={row.symbol}>
            <button
              type="button"
              onClick={() => openRow(navigate, row.symbol)}
              className="w-full rounded-lg border border-border bg-card p-3 text-left"
            >
              <div className="flex items-baseline justify-between gap-3">
                <div>
                  <span className="font-medium">{row.symbol}</span>
                  <span className="ml-2 text-sm text-muted-foreground">{row.name}</span>
                </div>
                <ScoreMark score={row.score} />
              </div>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="num text-lg">{formatPrice(row.price)}</span>
                <span className={`num ${toneClass(row.changePct)}`}>{formatPct(row.changePct, 2)}</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <div className="flex justify-between gap-2">
                  <dt>市值</dt>
                  <dd className="num text-foreground">{formatUsdLabeled(row.marketCap)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>成交額</dt>
                  <dd className="num text-foreground">{formatUsdLabeled(row.dollarVolume)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>對200天</dt>
                  <dd className={`num ${toneClass(row.vsSma200)}`}>{formatPct(row.vsSma200)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>貝他 / RS</dt>
                  <dd className="num text-foreground">
                    {formatBeta(row.beta)} · {formatPct(row.rs6m)}
                  </dd>
                </div>
              </dl>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

function ScoreMark({ score }: { score: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="num text-sm">{score}</span>
      <span className="h-1.5 w-12 bg-secondary">
        <span className="block h-full bg-brass" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </span>
    </span>
  )
}

function openRow(navigate: ReturnType<typeof useNavigate>, symbol: string) {
  sessionStorage.setItem("kailut-symbol", symbol)
  void navigate(`/stock/${symbol}`)
}
