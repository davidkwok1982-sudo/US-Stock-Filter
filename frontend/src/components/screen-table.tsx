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
  formatPct,
  formatPrice,
  formatMoneyLabeled,
  toneClass,
} from "@/lib/format.ts"
import { displayName, industryLabel } from "@/lib/filters.ts"
import { stockHref } from "@/lib/market.ts"
import { useScreen } from "@/lib/screen-context.tsx"
import type { ScreenRow, SortKey } from "@/lib/types.ts"

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
  const { copy, market, side } = useScreen()
  const columns = [
    { key: "symbol" as const, label: "代號", tip: copy.symbolTip, align: "left" as const },
    { key: "name" as const, label: "名稱", tip: "公司名稱", align: "left" as const },
    { key: "industry" as const, label: "行業", tip: "行業分類（優先中文標籤）", align: "left" as const },
    { key: "price" as const, label: "現價", tip: market === "hk" ? "最近報價，港元" : "最近報價，美元", align: "right" as const },
    { key: "changePct" as const, label: "升跌", tip: "較上一個收市", align: "right" as const },
    { key: "marketCap" as const, label: "市值", tip: market === "hk" ? "港元市值（Yahoo）" : "美元市值", align: "right" as const },
    { key: "dollarVolume" as const, label: "日均成交額", tip: "近63日或三個月估算", align: "right" as const },
    { key: "vsSma200" as const, label: "對200天", tip: "現價相對200天線", align: "right" as const },
    { key: "rs1w" as const, label: "一星期RS", tip: copy.rsColumnTip, align: "right" as const },
    { key: "score" as const, label: "評分", tip: "0至100，只用於排序", align: "right" as const },
  ]
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {columns.map((column) => (
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
                onClick={() => openRow(navigate, row.symbol, stockHref(copy, row.symbol, side), copy.sessionKey)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    openRow(navigate, row.symbol, stockHref(copy, row.symbol, side), copy.sessionKey)
                  }
                }}
              >
                <TableCell className="font-medium">{row.symbol}</TableCell>
                <TableCell className="max-w-48 truncate text-muted-foreground">{displayName(row)}</TableCell>
                <TableCell className="max-w-40 truncate text-muted-foreground">
                  {industryLabel(row) || "—"}
                </TableCell>
                <TableCell className="num text-right">{formatPrice(row.price)}</TableCell>
                <TableCell className={`num text-right ${toneClass(row.changePct)}`}>{formatPct(row.changePct, 2)}</TableCell>
                <TableCell className="num text-right">{formatMoneyLabeled(row.marketCap, market === "hk" ? "HKD" : "USD")}</TableCell>
                <TableCell className="num text-right">{formatMoneyLabeled(row.dollarVolume, market === "hk" ? "HKD" : "USD")}</TableCell>
                <TableCell className={`num text-right ${toneClass(row.vsSma200)}`}>{formatPct(row.vsSma200)}</TableCell>
                <TableCell className={`num text-right ${toneClass(row.rs1w ?? row.rs6m)}`}>{formatPct(row.rs1w ?? row.rs6m)}</TableCell>
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
              onClick={() => openRow(navigate, row.symbol, stockHref(copy, row.symbol, side), copy.sessionKey)}
              className="w-full rounded-lg border border-border bg-card p-3 text-left"
            >
              <div className="flex items-baseline justify-between gap-3">
                <div>
                  <span className="font-medium">{row.symbol}</span>
                  <span className="ml-2 text-sm text-muted-foreground">{displayName(row)}</span>
                </div>
                <ScoreMark score={row.score} />
              </div>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="num text-lg">{formatPrice(row.price)}</span>
                <span className={`num ${toneClass(row.changePct)}`}>{formatPct(row.changePct, 2)}</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <div className="col-span-2 flex justify-between gap-2">
                  <dt>行業</dt>
                  <dd className="truncate text-foreground">{industryLabel(row) || "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>市值</dt>
                  <dd className="num text-foreground">{formatMoneyLabeled(row.marketCap, market === "hk" ? "HKD" : "USD")}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>成交額</dt>
                  <dd className="num text-foreground">{formatMoneyLabeled(row.dollarVolume, market === "hk" ? "HKD" : "USD")}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>對200天</dt>
                  <dd className={`num ${toneClass(row.vsSma200)}`}>{formatPct(row.vsSma200)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>一星期 RS</dt>
                  <dd className={`num ${toneClass(row.rs1w ?? row.rs6m)}`}>
                    {formatPct(row.rs1w ?? row.rs6m)}
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

function openRow(
  navigate: ReturnType<typeof useNavigate>,
  symbol: string,
  href: string,
  sessionKey: string,
) {
  sessionStorage.setItem(sessionKey, symbol)
  void navigate(href)
}
