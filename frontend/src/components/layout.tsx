import { NavLink, Outlet, useLocation } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { formatHongKongTime, formatMarketDate } from "@/lib/format.ts"
import { MARKETS, type MarketId } from "@/lib/market.ts"
import { useScreen } from "@/lib/screen-context.tsx"

function navClass(active: boolean): string {
  return active
    ? "bg-foreground text-background"
    : "text-foreground/80 hover:bg-secondary hover:text-foreground"
}

function marketTabClass(active: boolean): string {
  return active
    ? "bg-primary text-primary-foreground"
    : "text-muted-foreground hover:bg-secondary hover:text-foreground"
}

export function Layout() {
  const { data, refresh, refreshing, copy, market } = useScreen()
  const location = useLocation()
  const marketDate = data?.meta?.marketDate
  const refreshed = data?.meta?.refreshedAt
  const home = copy.basePath || "/"
  const stockTarget = stockLink(location.pathname, market, copy.sessionKey)
  const links = [
    { to: home, label: "篩選結果", end: true },
    { to: stockTarget, label: "個股詳情", end: false },
    { to: `${copy.basePath}/strategy`, label: "策略說明", end: true },
  ]

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-foreground bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-2 gap-y-2 px-3 py-2.5 sm:gap-x-3 sm:px-4 sm:py-3">
          <NavLink to={home} className="min-w-0 max-w-full shrink">
            <span className="font-heading text-xl leading-tight font-semibold tracking-wide sm:text-3xl sm:leading-none">
              {copy.title}
            </span>
            <span className="mt-0.5 block truncate text-[10px] tracking-[0.14em] text-muted-foreground sm:mt-1 sm:text-[11px] sm:tracking-[0.18em]">
              {copy.subtitle}
            </span>
          </NavLink>
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1.5 sm:gap-2">
            <div className="flex shrink-0 overflow-hidden rounded-md border border-border" role="group" aria-label="市場">
              {(["us", "hk"] as MarketId[]).map((id) => {
                const m = MARKETS[id]
                const active = market === id
                return (
                  <NavLink
                    key={id}
                    to={m.basePath || "/"}
                    className={`px-2 py-1 text-xs font-medium sm:px-2.5 ${marketTabClass(active)}`}
                  >
                    {id === "us" ? "美股" : "港股"}
                  </NavLink>
                )
              })}
            </div>
            <nav className="hidden items-center gap-1 md:flex" aria-label="主要">
              {links.map((link) => (
                <NavLink
                  key={link.label}
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm ${navClass(isActive)}`}
                >
                  {link.label}
                </NavLink>
              ))}
            </nav>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="shrink-0 px-2 sm:px-3"
              onClick={() => void refresh()}
              disabled={refreshing}
            >
              {refreshing ? "更新中" : (
                <>
                  <span className="sm:hidden">更新</span>
                  <span className="hidden sm:inline">重新整理</span>
                </>
              )}
            </Button>
          </div>
        </div>
        <div className="h-[3px] bg-primary" />
      </header>

      <div className="mx-auto flex max-w-6xl flex-wrap items-baseline justify-end gap-2 px-4 py-2 text-xs text-muted-foreground">
        <p>
          {marketDate ? `${copy.marketDateLabel} ${formatMarketDate(marketDate)}` : "等待行情"}
          {refreshed ? ` · 香港時間 ${formatHongKongTime(refreshed)} 更新` : ""}
        </p>
      </div>

      <main className="mx-auto max-w-6xl px-4 pb-24">
        <Outlet />
      </main>

      <footer className="mx-auto hidden max-w-6xl px-4 pb-10 text-xs leading-relaxed text-muted-foreground md:block">
        {copy.footerSource}
      </footer>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t border-foreground bg-background md:hidden"
        aria-label="主要"
      >
        {links.map((link) => (
          <NavLink
            key={link.label}
            to={link.to}
            end={link.end}
            className={({ isActive }) => `px-2 py-3 text-center text-sm ${isActive ? "text-primary" : "text-muted-foreground"}`}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function stockLink(pathname: string, market: MarketId, sessionKey: string): string {
  const prefix = market === "hk" ? "/hk/stock" : "/stock"
  if (pathname.startsWith(`${prefix}/`)) return pathname
  const saved = sessionStorage.getItem(sessionKey)
  return saved ? `${prefix}/${saved}` : prefix
}
