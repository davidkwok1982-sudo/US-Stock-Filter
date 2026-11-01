import type { ScreenResponse, StockDetail } from "./types.ts"

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string" && body.detail) return body.detail
  } catch {
    /* ignore broken error bodies */
  }
  return fallback
}

export async function fetchScreen(): Promise<ScreenResponse> {
  const response = await fetch("/api/screen")
  if (!response.ok) throw new Error(await readError(response, "篩選暫時未能載入"))
  return response.json() as Promise<ScreenResponse>
}

export async function fetchStock(symbol: string): Promise<StockDetail> {
  const response = await fetch(`/api/stock/${encodeURIComponent(symbol)}`)
  if (!response.ok) throw new Error(await readError(response, "未能載入這隻股份"))
  return response.json() as Promise<StockDetail>
}

export async function postRefresh(): Promise<{
  started: boolean
  reason: string
  message: string
}> {
  const response = await fetch("/api/refresh", { method: "POST" })
  if (!response.ok) throw new Error(await readError(response, "未能開始更新"))
  return response.json() as Promise<{ started: boolean; reason: string; message: string }>
}
