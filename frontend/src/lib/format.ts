export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value < 0 ? "-" : ""
  const amount = Math.abs(value)
  if (amount >= 1e12) return `${sign}${(amount / 1e12).toFixed(2)}萬億`
  if (amount >= 1e8) {
    const scaled = amount / 1e8
    const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2
    return `${sign}${scaled.toFixed(digits)}億`
  }
  if (amount >= 1e4) return `${sign}${Math.round(amount / 1e4).toLocaleString("zh-HK")}萬`
  return `${sign}${Math.round(amount).toLocaleString("zh-HK")}`
}

export function formatUsdLabeled(value: number | null | undefined): string {
  const text = formatUsd(value)
  return text === "—" ? text : `US$${text}`
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const digits = Math.abs(value) >= 1 ? 2 : 4
  return value.toLocaleString("zh-HK", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const shown = value * 100
  const sign = shown > 0 ? "+" : ""
  return `${sign}${shown.toFixed(digits)}%`
}

export function formatBeta(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "未明"
  return value.toFixed(2)
}

export function betaCaption(basis: "yahoo" | "90d-spy" | null): string {
  if (basis === "yahoo") return "Yahoo"
  if (basis === "90d-spy") return "90日"
  return ""
}

export function toneClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "text-foreground"
  return value > 0 ? "text-up" : "text-down"
}

export function formatMarketDate(ymd: string | null | undefined): string {
  if (!ymd) return "—"
  const [year, month, day] = ymd.split("-")
  if (!year || !month || !day) return ymd
  return `${year}年${Number(month)}月${Number(day)}日`
}

export function formatHongKongTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return "—"
  return new Intl.DateTimeFormat("zh-HK", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date)
}
