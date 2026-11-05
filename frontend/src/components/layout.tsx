import { NavLink, Outlet, useLocation } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { formatHongKongTime, formatMarketDate } from "@/lib/format.ts"
import { MARKETS, strategyHref, type MarketId } from "@/lib/market.ts"
import { useScreen } from "@/lib/screen-context.tsx"
import type { Side } from "@/lib/filters.ts"

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
  const { data, refresh, refreshing, copy, market, side, setSide } = useScreen()
  const location = useLocation()
  const marketDate = data?.meta?.marketDate
  const refreshed = data?.meta?.refreshedAt
  const home = withSearch(copy.basePath || "/", location.search)
  const stockTarget = withSearch(stockLink(location.pathname, market, copy.sessionKey), location.search)
  const heading = side === "short" ? `${copy.title} · 短倉` : copy.title
  const subtitle = side === "short" ? "短倉技術篩選 · 非投資建議" : copy.subtitle
  const links = [
    { to: home, label: "篩選結果", end: true },
    { to: stockTarget, label: "個股詳情", end: false },
    { to: withSearch(strategyHref(copy, "long"), location.search), label: "策略說明", end: true },
  ]

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-foreground bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <NavLink to={home} className="min-w-0 shrink-0">
            <span className="font-heading text-3xl leading-none font-semibold tracking-wide">{heading}</span>
            <span className="mt-1 block text-[11px] tracking-[0.18em] text-muted-foreground">{subtitle}</span>
          </NavLink>
          <div className="ml-2 flex shrink-0 overflow-hidden rounded-md border border-border" role="group" aria-label="市場">
            {(["us", "hk"] as MarketId[]).map((id) => {
              const m = MARKETS[id]
              const active = market === id
              return (
                <NavLink
                  key={id}
                  to={withSearch(m.basePath || "/", location.search)}
                  className={`px-2.5 py-1 text-xs font-medium ${marketTabClass(active)}`}
                >
                  {id === "us" ? "美股" : "港股"}
                </NavLink>
              )
            })}
          </div>
          <div className="flex shrink-0 overflow-hidden rounded-md border border-border" role="group" aria-label="長倉或短倉">
            {(["long", "short"] as Side[]).map((id) => {
              const active = side === id
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSide(id)}
                  className={`px-2.5 py-1 text-xs font-medium ${marketTabClass(active)}`}
                >
                  {id === "long" ? "長倉" : "短倉"}
                </button>
              )
            })}
          </div>
          <nav className="ml-auto hidden items-center gap-1 md:flex" aria-label="主要">
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
          <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={refreshing}>
            {refreshing ? "更新中" : "重新整理"}
          </Button>
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

function withSearch(pathname: string, search: string): string {
  if (!search) return pathname
  const query = search.startsWith("?") ? search : `?${search}`
  return `${pathname}${query}`
}

function stockLink(pathname: string, market: MarketId, sessionKey: string): string {
  const prefix = market === "hk" ? "/hk/stock" : "/stock"
  if (pathname.startsWith(`${prefix}/`)) return pathname
  const saved = sessionStorage.getItem(sessionKey)
  return saved ? `${prefix}/${saved}` : prefix
}
