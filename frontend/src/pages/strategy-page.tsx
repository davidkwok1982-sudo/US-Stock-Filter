import { useEffect } from "react"
import { Link } from "react-router-dom"

import { Separator } from "@/components/ui/separator"

const SCORE_ROWS = [
  ["與200天線的距離", "20", "高於 0–30% 得 20；30–60% 得 12；超過 60% 得 5。未站上得 0。"],
  ["站上50天線", "15", "現價高於50天線得 15，否則 0。"],
  ["50天線向上", "15", "50天線較約20個交易日前上升。"],
  ["200天線向上", "15", "200天線較約20個交易日前上升。"],
  ["一星期相對 SPY", "25", "近約5個交易日回報減 SPY：落後 5 個百分點或更多為 0，持平約 10，領先 8 個百分點或更多為 25。"],
  ["流動性", "10", "日均成交額 3,000 萬美元約 4 分，大約八倍（2.4 億美元）封頂 10 分。"],
]

export function StrategyPage() {
  useEffect(() => {
    document.title = "美股篩選器 · 策略說明"
  }, [])

  return (
    <article className="mx-auto max-w-3xl space-y-8 pb-8">
      <header>
        <p className="text-xs tracking-[0.22em] text-muted-foreground">STAGE 2</p>
        <h1 className="mt-1 font-heading text-4xl font-semibold">策略說明</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          美股篩選器按公開文章裡的第二階段思路，做成一個可重算的美股篩選，並用評分在通過名單裡排序。
        </p>
      </header>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">這頁在做甚麼</h2>
        <p>
          股價相對 200 天線的位置可分成四個階段。第一階段是底部整固，均線走平。第二階段是上升趨勢，股價站上並通常帶動向上的長期均線。第三階段見頂派發。第四階段跌破長期均線。
        </p>
        <p>
          本站把第二階段相關條件寫成可檢查的數字，股票池覆蓋全美上市普通股（已剔除 ADR 與 ETF），並用評分在通過名單裡排序。
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-2xl">評分</h2>
        <p className="text-sm leading-relaxed">
          通過篩選之後，評分只決定先後，滿分 100。一隻股份可以通過均線堆疊但近一星期落後 SPY，評分就會偏低。
        </p>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="bg-secondary/70 text-xs tracking-wide">
              <tr>
                <th className="px-3 py-2 font-medium">項目</th>
                <th className="px-3 py-2 font-medium">滿分</th>
                <th className="px-3 py-2 font-medium">怎樣給分</th>
              </tr>
            </thead>
            <tbody>
              {SCORE_ROWS.map(([name, points, rule]) => (
                <tr key={name} className="border-t border-border">
                  <td className="px-3 py-2 align-top">{name}</td>
                  <td className="num px-3 py-2 align-top">{points}</td>
                  <td className="px-3 py-2 align-top text-muted-foreground">{rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">可選收緊</h2>
        <p>這些開關預設關掉。打開之後只會縮小表格，不會改寫頂部的通過家數。</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>跑贏 SPY 5 天：近約 5 個交易日收市對收市總回報減 SPY 為正。</li>
          <li>跑贏 SPY 20 天：近約 20 個交易日收市對收市總回報減 SPY 為正。</li>
          <li>收市近支持：以日線結構支持區估計（清晰擺動低點加上近約20／60日區間低點，並把10／20／50／150／200天線計入匯合；須至少兩次觸及才標出；圖表只畫中軸虛線，篩選仍用中軸±0.5×ATR 區）。最新收市須落在該支持區內，優先取較接近中軸、且收市在中軸上方的支持。篩選與圖表共用同一套定義。全量更新時會重算，規則版本變更時亦會用已存日線重填此欄。</li>
        </ul>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">廣度提示</h2>
        <p>
          通過家數達 200 或以上，標成廣度偏多；少於 100，標成宜審慎；介乎其中則為中性。這組數字來自公開文章的經驗講法。本站統計全美上市普通股（已剔除 ADR 與 ETF）裡通過篩選的家數，可讀成這批股份的廣度觀察，不是整個市場的唯一度量。
        </p>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">數據與股票池</h2>
        <p>
          成份來自 Nasdaq Trader 免費符號目錄（nasdaqlisted／otherlisted），保留美股普通股，剔除 ETF、ETN、NextShares、ADR／ADS、測試股、權證、單位、優先股等明顯標記。下載失敗時改用上一次成功存下來的名單。
        </p>
        <p>
          行情來自 Yahoo Finance 的公開圖表與報價接口，不需要 API 金鑰。K 線和均線用拆股還原價，成交額用未還原收市價乘成交量。免費數據可能延遲、缺漏，或在盤中改寫最後一根日線。結果會寫入本機 SQLite；全量更新按批次下載，預設 12 小時內不重複全量下載；手動更新另有約五分鐘的冷卻。
        </p>
        <p>個股頁的行業、市盈率和收入增長來自 Yahoo 的免費公司摘要，季報數字可能落後。沒有就不硬填。</p>
      </section>

      <Separator />

      <section className="space-y-3 text-sm leading-relaxed">
        <p>
          <Link to="/" className="underline underline-offset-4">
            返回篩選結果
          </Link>
        </p>
      </section>
    </article>
  )
}
