export type RefreshState = {
  running: boolean
  progress: number
  message: string
  error: string | null
}

export type ScorePart = {
  key: string
  label: string
  points: number
  max: number
}

export type ScreenRow = {
  symbol: string
  name: string
  exchange: string | null
  groups: string[]
  groupLabels: string[]
  sector: string | null
  sectorEn?: string | null
  industry: string | null
  industryEn?: string | null
  price: number | null
  changePct: number | null
  marketCap: number | null
  dollarVolume: number | null
  dollarVolumeBasis: "63d" | "quote3m" | null
  vsSma200: number | null
  vsSma50: number | null
  sma50: number | null
  sma150?: number | null
  sma200: number | null
  sma50Slope: number | null
  sma150Slope?: number | null
  sma200Slope: number | null
  aboveSma50: boolean
  aboveSma200: boolean
  maStacked?: boolean
  slopeUp: boolean
  high52: number | null
  low52: number | null
  pctFromHigh: number | null
  nearHigh: boolean
  closeAtSupport: boolean
  closeAtSupportNote?: string | null
  ret1w?: number | null
  ret3m: number | null
  ret6m: number | null
  rs1w?: number | null
  rs3m: number | null
  rs6m: number | null
  rsBeat: boolean
  pe: number | null
  score: number
  scoreParts?: ScorePart[]
  passHard: boolean
  failReasons: string[]
  failCodes: string[]
  microOrOtc: boolean
  otc: boolean
  incomplete: boolean
  barsCount: number
  revenueGrowth?: number | null
  earningsGrowth?: number | null
  profitMargin?: number | null
}

export type UniverseCounts = {
  unique: number
  evaluated?: number
  partial?: boolean
  /** @deprecated older snapshots */
  sp500?: number
  ndx?: number
  sp400?: number
}

export type ScreenMeta = {
  refreshedAt: string
  marketDate: string
  universeSource: string
  universe: UniverseCounts
  summary: {
    universe: number
    pass: number
    incomplete: number
    failMaStack?: number
    failMaSlope?: number
    failSma200: number
    failCap: number
    failLiquidity?: number
    failBeta?: number
    failOtc: number
    failType: number
    microOrOtc: number
  }
  breadth: {
    tone: "bullish" | "neutral" | "cautious"
    label: string
    count: number
    bullishAt: number
    cautiousBelow: number
  }
  spy: {
    symbol: string
    price: number | null
    marketDate: string | null
    ret1w?: number | null
    ret3m: number | null
    ret6m: number | null
  }
  source: string
  betaMethod?: string
  dollarVolumeMethod: string
  adjustment: string
  ttlHours: number
  chartFailures: number
  criteria: Record<string, number>
}

export type ScreenResponse = {
  ready: boolean
  stale: boolean
  meta: ScreenMeta | null
  rows: ScreenRow[]
  refresh: RefreshState
}

/** YYYY-MM-DD for daily/weekly; unix seconds for hourly (lightweight-charts). */
export type ChartTime = string | number

export type Bar = {
  time: ChartTime
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export type LinePoint = { time: ChartTime; value: number }

export type ChartInterval = "1d" | "1wk" | "1h"

export type PriceLevel = {
  price: number
  kind: "support" | "resistance"
  touches: number
  label: string
}

export type IndexSeries = {
  symbol: string
  label: string
  closes: LinePoint[]
  /** SPY OHLC for the top candlestick pane; optional for older API payloads. */
  bars?: Bar[]
}

export type CompanyProfile = {
  summary: string | null
  sector: string | null
  industry: string | null
  sectorZh: string | null
  industryZh: string | null
  sectorEn: string | null
  industryEn: string | null
  website: string | null
  employees: number | null
  hq: string | null
  city: string | null
  state: string | null
  country: string | null
  phone: string | null
  source?: string | null
}

export type StockDetail = {
  row: ScreenRow
  /** Selected chart timeframe; defaults to 1d when older API omits it. */
  interval?: ChartInterval
  bars: Bar[]
  sma50: LinePoint[]
  sma150?: LinePoint[]
  sma200: LinePoint[]
  index: IndexSeries | null
  levels: PriceLevel[]
  notes: {
    technical: string[]
    fundamental: string[]
    disclaimer?: string
    disclaimerLong?: string
  }
  /** Company intro from Yahoo assetProfile; null when unavailable. */
  profile?: CompanyProfile | null
  /** True when company profile may still upgrade via /profile. */
  profilePending?: boolean
  meta: ScreenMeta | null
}

export type SortKey =
  | "symbol"
  | "name"
  | "price"
  | "changePct"
  | "marketCap"
  | "dollarVolume"
  | "vsSma200"
  | "rs1w" | "rs6m"
  | "score"

export type Filters = {
  q: string
  rs: boolean
  support: boolean
  sort: SortKey
  dir: "asc" | "desc"
}
