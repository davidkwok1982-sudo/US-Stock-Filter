import type { Filters, ScreenRow, SortKey } from "./types.ts"

/** Prefer zh industry label; fall back to EN. */
export function industryLabel(row: ScreenRow): string {
  return (row.industry?.trim() || row.industryEn?.trim() || "")
}

/** Prefer Traditional Chinese short name when present (HK). */
export function displayName(row: ScreenRow): string {
  return (row.nameZh?.trim() || row.name?.trim() || row.symbol)
}

function matchesQuery(row: ScreenRow, query: string): boolean {
  if (!query) return true
  if (row.symbol.toLowerCase().includes(query)) return true
  if (row.name.toLowerCase().includes(query)) return true
  const zh = row.nameZh?.trim()
  if (zh && zh.toLowerCase().includes(query)) return true
  return false
}

const SORTS = new Set<SortKey>([
  "symbol",
  "name",
  "industry",
  "price",
  "changePct",
  "marketCap",
  "dollarVolume",
  "vsSma200",
  "rs1w",
  "score",
])

function parseGain1w(raw: string | null): number | null {
  if (raw == null || raw === "") return null
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  return n
}

export function readFilters(params: URLSearchParams): Filters {
  const sort = params.get("sort")
  return {
    q: params.get("q") ?? "",
    rs: params.get("rs") === "1",
    support: params.get("support") === "1" || params.get("retest") === "1",
    gain1w: parseGain1w(params.get("gain1w")),
    sort: sort && SORTS.has(sort as SortKey) ? (sort as SortKey) : "score",
    dir: params.get("dir") === "asc" ? "asc" : "desc",
  }
}

export function writeFilters(filters: Filters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.q.trim()) params.set("q", filters.q.trim())
  if (filters.rs) params.set("rs", "1")
  if (filters.support) params.set("support", "1")
  if (filters.gain1w != null && Number.isFinite(filters.gain1w)) {
    params.set("gain1w", String(filters.gain1w))
  }
  if (filters.sort !== "score") params.set("sort", filters.sort)
  if (filters.dir !== "desc") params.set("dir", filters.dir)
  return params
}

export function visibleRows(rows: ScreenRow[], filters: Filters): ScreenRow[] {
  const query = filters.q.trim().toLowerCase()
  const list = rows.filter((row) => {
    if (!row.passHard) return false
    if (filters.rs && !(row.rsBeat && row.rsBeat20)) return false
    if (filters.support && !row.closeAtSupport) return false
    if (filters.gain1w != null) {
      if (row.ret1w == null || !(row.ret1w >= filters.gain1w / 100)) return false
    }
    if (!query) return true
    return matchesQuery(row, query)
  })
  const direction = filters.dir === "asc" ? 1 : -1
  list.sort((left, right) => {
    if (filters.sort === "industry") {
      const a = industryLabel(left)
      const b = industryLabel(right)
      if (!a && !b) return left.symbol.localeCompare(right.symbol)
      if (!a) return 1
      if (!b) return -1
      const compared = a.localeCompare(b, "zh-Hant")
      return compared === 0 ? left.symbol.localeCompare(right.symbol) : compared * direction
    }
    if (filters.sort === "name") {
      const compared = displayName(left).localeCompare(displayName(right), "zh-Hant")
      return compared === 0 ? left.symbol.localeCompare(right.symbol) : compared * direction
    }
    const a = left[filters.sort]
    const b = right[filters.sort]
    if (typeof a === "string" && typeof b === "string") {
      const compared = a.localeCompare(b, "en")
      return compared === 0 ? left.symbol.localeCompare(right.symbol) : compared * direction
    }
    const an = typeof a === "number" ? a : null
    const bn = typeof b === "number" ? b : null
    if (an == null && bn == null) return left.symbol.localeCompare(right.symbol)
    if (an == null) return 1
    if (bn == null) return -1
    if (an === bn) return left.symbol.localeCompare(right.symbol)
    return (an - bn) * direction
  })
  return list
}
