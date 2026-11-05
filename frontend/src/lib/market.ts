export type MarketId = "us" | "hk"

export type MarketCopy = {
  id: MarketId
  title: string
  subtitle: string
  apiPrefix: string
  basePath: string
  stockPath: (symbol: string) => string
  benchmarkShort: string
  benchmarkFull: string
  rsChip: string
  rsHint: string
  universeBlurb: (unique: number, evaluated?: number | null) => string
  marketDateLabel: string
  footerSource: string
  symbolTip: string
  rsColumnTip: string
  hardCapBlurb: string
  strategyIntro: string
  scoreRsLabel: string
  sessionKey: string
}

export const MARKETS: Record<MarketId, MarketCopy> = {
  us: {
    id: "us",
    title: "美股篩選器",
    subtitle: "美股第二階段觀察台",
    apiPrefix: "/api",
    basePath: "",
    stockPath: (symbol) => `/stock/${symbol}`,
    benchmarkShort: "SPY",
    benchmarkFull: "標普500（SPY）",
    rsChip: "跑贏 SPY",
    rsHint: "近約 5 個與 20 個交易日收市對收市總回報均高於 SPY（相對強度皆為正）",
    universeBlurb: (unique, evaluated) =>
      `股票池為全美上市普通股（已剔除 ADR 與 ETF），目前 ${unique} 隻` +
      (evaluated != null && evaluated !== unique ? `（已評估 ${evaluated}）` : "") +
      "。",
    marketDateLabel: "美東交易日",
    footerSource: "資料來源：Nasdaq Trader 符號目錄 · Yahoo Finance 公開行情。",
    symbolTip: "美股代號",
    rsColumnTip: "近約5個交易日回報減 SPY",
    hardCapBlurb: "市值逾20億美元",
    strategyIntro:
      "本站按以下七步篩選美股：先鎖定 Stage 2，再收緊市值與流動性、相對強度、領導板塊、升勢早期程度、近一星期升幅，以及是否靠近支持位。",
    scoreRsLabel: "一星期相對 SPY",
    sessionKey: "kailut-symbol",
  },
  hk: {
    id: "hk",
    title: "港股篩選器",
    subtitle: "港股第二階段觀察台",
    apiPrefix: "/api/hk",
    basePath: "/hk",
    stockPath: (symbol) => `/hk/stock/${symbol}`,
    benchmarkShort: "恆指",
    benchmarkFull: "恆生指數（HSI）",
    rsChip: "跑贏恆指",
    rsHint: "近約 5 個與 20 個交易日收市對收市總回報均高於恆生指數（相對強度皆為正）",
    universeBlurb: (unique, evaluated) =>
      `股票池為港交所上市普通股（已剔除 ETF、窩輪、牛熊證、債券、REIT 等），目前 ${unique} 隻` +
      (evaluated != null && evaluated !== unique ? `（已評估 ${evaluated}）` : "") +
      "。",
    marketDateLabel: "香港交易日",
    footerSource: "資料來源：香港交易所證券名單 · Yahoo Finance 公開行情。",
    symbolTip: "港股代號（如 0700.HK）",
    rsColumnTip: "近約5個交易日回報減恆指",
    hardCapBlurb: "市值逾100億港元",
    strategyIntro:
      "本站按以下七步篩選港股：先鎖定 Stage 2，再收緊市值與流動性、相對強度（對比恆指）、領導板塊、升勢早期程度、近一星期升幅，以及是否靠近支持位。",
    scoreRsLabel: "一星期相對恆指",
    sessionKey: "kailut-hk-symbol",
  },
}

export function marketFromPath(pathname: string): MarketId {
  return pathname === "/hk" || pathname.startsWith("/hk/") ? "hk" : "us"
}

export function stockHref(copy: MarketCopy, symbol: string, side: "long" | "short"): string {
  const path = copy.stockPath(symbol)
  return side === "short" ? `${path}?side=short` : path
}

export function strategyHref(copy: MarketCopy, side: "long" | "short"): string {
  const path = `${copy.basePath}/strategy` || "/strategy"
  return side === "short" ? `${path}?side=short` : path
}
