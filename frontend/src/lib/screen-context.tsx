import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"

import { fetchScreen, postRefresh } from "./api.ts"
import type { ScreenResponse } from "./types.ts"

type ScreenContextValue = {
  data: ScreenResponse | null
  loadError: string | null
  refreshing: boolean
  refresh: () => Promise<void>
}

const ScreenContext = createContext<ScreenContextValue | null>(null)

export function ScreenProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<ScreenResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let stop = false
    let timer = 0

    async function tick() {
      try {
        const next = await fetchScreen()
        if (stop) return
        setData(next)
        setLoadError(null)
        if (!next.ready || next.refresh.running) {
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
  }, [nonce])

  const refresh = useCallback(async () => {
    try {
      const result = await postRefresh()
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
  }, [])

  const value = useMemo<ScreenContextValue>(
    () => ({
      data,
      loadError,
      refreshing: Boolean(data?.refresh.running),
      refresh,
    }),
    [data, loadError, refresh],
  )

  return <ScreenContext.Provider value={value}>{children}</ScreenContext.Provider>
}

export function useScreen(): ScreenContextValue {
  const value = useContext(ScreenContext)
  if (!value) throw new Error("useScreen 必須放在 ScreenProvider 內")
  return value
}
