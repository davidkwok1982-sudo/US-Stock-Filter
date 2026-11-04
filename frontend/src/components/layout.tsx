import { NavLink, Outlet, useLocation } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { formatHongKongTime, formatMarketDate } from "@/lib/format.ts"
import { useScreen } from "@/lib/screen-context.tsx"

const LINKS = [
  { to: "/", label: "篩選結果", end: true },
  { to: "/stock", label: "個股詳情", end: false },
  { to: "/strategy", label: "策略說明", end: true },
]

function navClass(active: boolean): string {
  return active
    ? "bg-foreground text-background"
    : "text-foreground/80 hover:bg-secondary hover:text-foreground"
}

export function Layout() {
  const { data, refresh, refreshing } = useScreen()
  const location = useLocation()
  const marketDate = data?.meta?.marketDate
  const refreshed = data?.meta?.refreshedAt
  const stockTarget = stockLink(location.pathname)

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-foreground bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <NavLink to="/" className="min-w-0 shrink-0">
            <span className="font-heading text-3xl leading-none font-semibold tracking-wide">美股篩選器</span>
            <span className="mt-1 block text-[11px] tracking-[0.18em] text-muted-foreground">美股第二階段觀察台</span>
          </NavLink>
          <nav className="ml-auto hidden items-center gap-1 md:flex" aria-label="主要">
            {LINKS.map((link) => (
              <NavLink
                key={link.label}
                to={link.label === "個股詳情" ? stockTarget : link.to}
                end={link.end}
                className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm ${navClass(isActive)}`}
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
            {refreshing ? "更新中" : "重新整理"}
          </Button>
        </div>
        <div className="h-[3px] bg-up" />
      </header>

      <div className="mx-auto flex max-w-6xl flex-wrap items-baseline justify-between gap-2 px-4 py-2 text-xs text-muted-foreground">
        <p>升紅跌綠</p>
        <p>
          {marketDate ? `美東交易日 ${formatMarketDate(marketDate)}` : "等待行情"}
          {refreshed ? ` · 香港時間 ${formatHongKongTime(refreshed)} 更新` : ""}
        </p>
      </div>

      <main className="mx-auto max-w-6xl px-4 pb-24">
        <Outlet />
      </main>

      <footer className="mx-auto hidden max-w-6xl px-4 pb-10 text-xs leading-relaxed text-muted-foreground md:block">
        資料來源：Nasdaq Trader 符號目錄 · Yahoo Finance 公開行情。
      </footer>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t border-foreground bg-background md:hidden"
        aria-label="主要"
      >
        {LINKS.map((link) => (
          <NavLink
            key={link.label}
            to={link.label === "個股詳情" ? stockTarget : link.to}
            end={link.end}
            className={({ isActive }) => `px-2 py-3 text-center text-sm ${isActive ? "text-up" : "text-muted-foreground"}`}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function stockLink(pathname: string): string {
  if (pathname.startsWith("/stock/")) return pathname
  const saved = sessionStorage.getItem("kailut-symbol")
  return saved ? `/stock/${saved}` : "/stock"
}
