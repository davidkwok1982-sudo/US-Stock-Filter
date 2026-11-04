import type { Filters, ScreenRow, SortKey } from "./types.ts"

const SORTS = new Set<SortKey>([
  "symbol",
  "name",
  "price",
  "changePct",
  "marketCap",
  "dollarVolume",
  "vsSma200",
  "beta",
  "rs6m",
  "score",
])

export function readFilters(params: URLSearchParams): Filters {
  const sort = params.get("sort")
  return {
    q: params.get("q") ?? "",
    above50: params.get("ma50") === "1",
    slope: params.get("slope") === "1",
    nearHigh: params.get("high") === "1",
    rs: params.get("rs") === "1",
    support: params.get("support") === "1" || params.get("retest") === "1",
    excludeMicro: params.get("micro") !== "0",
    sort: sort && SORTS.has(sort as SortKey) ? (sort as SortKey) : "score",
    dir: params.get("dir") === "asc" ? "asc" : "desc",
  }
}

export function writeFilters(filters: Filters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.q.trim()) params.set("q", filters.q.trim())
  if (filters.above50) params.set("ma50", "1")
  if (filters.slope) params.set("slope", "1")
  if (filters.nearHigh) params.set("high", "1")
  if (filters.rs) params.set("rs", "1")
  if (filters.support) params.set("support", "1")
  if (!filters.excludeMicro) params.set("micro", "0")
  if (filters.sort !== "score") params.set("sort", filters.sort)
  if (filters.dir !== "desc") params.set("dir", filters.dir)
  return params
}

export function visibleRows(rows: ScreenRow[], filters: Filters): ScreenRow[] {
  const query = filters.q.trim().toLowerCase()
  const list = rows.filter((row) => {
    if (!row.passHard) return false
    if (filters.above50 && !row.aboveSma50) return false
    if (filters.slope && !row.slopeUp) return false
    if (filters.nearHigh && !row.nearHigh) return false
    if (filters.rs && !row.rsBeat) return false
    if (filters.support && !row.closeAtSupport) return false
    if (filters.excludeMicro && row.microOrOtc) return false
    if (!query) return true
    return row.symbol.toLowerCase().includes(query) || row.name.toLowerCase().includes(query)
  })
  const direction = filters.dir === "asc" ? 1 : -1
  list.sort((left, right) => {
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
