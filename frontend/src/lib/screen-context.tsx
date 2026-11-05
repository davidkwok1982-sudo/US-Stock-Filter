import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useLocation } from "react-router-dom"

import { fetchScreen, postRefresh } from "./api.ts"
import { MARKETS, marketFromPath, type MarketCopy, type MarketId } from "./market.ts"
import type { ScreenResponse } from "./types.ts"

type ScreenContextValue = {
  market: MarketId
  copy: MarketCopy
  data: ScreenResponse | null
  loadError: string | null
  refreshing: boolean
  refresh: () => Promise<void>
}

const ScreenContext = createContext<ScreenContextValue | null>(null)

export function ScreenProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const market = marketFromPath(location.pathname)
  const copy = MARKETS[market]
  const [data, setData] = useState<ScreenResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    setData(null)
    setLoadError(null)
  }, [market])

  useEffect(() => {
    let stop = false
    let timer = 0

    async function tick() {
      try {
        const next = await fetchScreen(market)
        if (stop) return
        setData(next)
        setLoadError(null)
        // Keep polling while a refresh is running. US cold boot also auto-starts refresh.
        // HK cold boot waits for manual refresh — stop hammering once we know it is idle.
        if (next.refresh.running || (!next.ready && market === "us")) {
          timer = window.setTimeout(() => void tick(), 1200)
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
  }, [nonce, market])

  const refresh = useCallback(async () => {
    try {
      const result = await postRefresh(market)
      if (!result.started && result.reason === "cooldown") {
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

  const value = useMemo<ScreenContextValue>(
    () => ({
      market,
      copy,
      data,
      loadError,
      refreshing: Boolean(data?.refresh.running),
      refresh,
    }),
    [market, copy, data, loadError, refresh],
  )

  return <ScreenContext.Provider value={value}>{children}</ScreenContext.Provider>
}

export function useScreen(): ScreenContextValue {
  const value = useContext(ScreenContext)
  if (!value) throw new Error("useScreen 必須放在 ScreenProvider 內")
  return value
}
