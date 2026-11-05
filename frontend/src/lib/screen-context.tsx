import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { fetchScreen, postRefresh } from "./api.ts"
import { readSide, type Side } from "./filters.ts"
import { MARKETS, marketFromPath, type MarketCopy, type MarketId } from "./market.ts"
import type { ScreenResponse } from "./types.ts"

type ScreenContextValue = {
  market: MarketId
  side: Side
  copy: MarketCopy
  data: ScreenResponse | null
  loadError: string | null
  refreshing: boolean
  refresh: () => Promise<void>
  setSide: (side: Side) => void
}

const ScreenContext = createContext<ScreenContextValue | null>(null)

export function ScreenProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const market = marketFromPath(location.pathname)
  const side = readSide(new URLSearchParams(location.search))
  const copy = MARKETS[market]
  const [data, setData] = useState<ScreenResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    setData(null)
    setLoadError(null)
  }, [market, side])

  useEffect(() => {
    let stop = false
    let timer = 0

    async function tick() {
      try {
        const next = await fetchScreen(market, side)
        if (stop) return
        setData(next)
        setLoadError(null)
        // Keep polling while a refresh is running. US cold boot also auto-starts refresh.
        // HK cold boot waits for manual refresh — stop hammering once we know it is idle.
        if (next.refresh.running || (!next.ready && market === "us")) {
          timer = window.setTimeout(() => void tick(), 2500)
        }
      } catch (error) {
        if (stop) return
        setLoadError(error instanceof Error ? error.message : "未能連上伺服器")
        timer = window.setTimeout(() => void tick(), 2500)
      }
    }

    void tick()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [nonce, market, side])

  const refresh = useCallback(async () => {
    try {
      const result = await postRefresh(market)
      if (!result.started && (result.reason === "cooldown" || result.reason === "busy")) {
        setData((current) =>
          current
            ? { ...current, refresh: { ...current.refresh, error: result.message, running: false } }
            : current,
        )
        return
      }
      setNonce((value) => value + 1)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "未能開始更新")
    }
  }, [market])

  const setSide = useCallback(
    (next: Side) => {
      const params = new URLSearchParams(location.search)
      if (next === "short") {
        params.set("side", "short")
        if (params.has("gain1w") && !params.has("drop1w")) params.set("drop1w", params.get("gain1w") ?? "")
        params.delete("gain1w")
      } else {
        params.delete("side")
        if (params.has("drop1w") && !params.has("gain1w")) params.set("gain1w", params.get("drop1w") ?? "")
        params.delete("drop1w")
      }
      const search = params.toString()
      navigate({ pathname: location.pathname, search: search ? `?${search}` : "" }, { replace: true })
    },
    [location.pathname, location.search, navigate],
  )

  const value = useMemo<ScreenContextValue>(
    () => ({
      market,
      side,
      copy,
      data,
      loadError,
      refreshing: Boolean(data?.refresh.running),
      refresh,
      setSide,
    }),
    [market, side, copy, data, loadError, refresh, setSide],
  )

  return <ScreenContext.Provider value={value}>{children}</ScreenContext.Provider>
}

export function useScreen(): ScreenContextValue {
  const value = useContext(ScreenContext)
  if (!value) throw new Error("useScreen 必須放在 ScreenProvider 內")
  return value
}
