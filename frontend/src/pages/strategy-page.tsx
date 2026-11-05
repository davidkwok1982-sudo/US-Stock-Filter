import { useEffect } from "react"
import { Link } from "react-router-dom"

import { Separator } from "@/components/ui/separator"

const SCORE_ROWS = [
  ["與200天線的距離", "20", "高於 0–30% 得 20；30–60% 得 12；超過 60% 得 5。未站上得 0。"],
  ["站上50天線", "15", "現價高於50天線得 15，否則 0。"],
  ["50天線向上", "15", "50天線較約5個交易日前上升。"],
  ["200天線向上", "15", "200天線較約5個交易日前上升。"],
  ["一星期相對 SPY", "25", "近約5個交易日回報減 SPY：落後 5 個百分點或更多為 0，持平約 10，領先 8 個百分點或更多為 25。"],
  ["流動性", "10", "日均成交額 3,000 萬美元約 4 分，大約八倍（2.4 億美元）封頂 10 分。"],
]

const STEPS = [
  {
    title: "先找出 Stage 2 股票",
    body: "Stage 2 指下跌完、做底，然後開始回升的股票。本站硬性條件：現價＞50 天線＞150 天線＞200 天線，而且 50／150／200 天線過去約一星期都向上。通過這關的才進名單。",
  },
  {
    title: "Filter 市值較大、流動性較高的股票",
    body: "硬性門檻要求市值逾 20 億美元，先剔除過細的股份。流動性另以日均成交額計入評分：成交愈活躍，排序愈前，方便實際買賣。",
  },
  {
    title: "Filter 跑贏大市、只留 RS 強的股票",
    body: "我們想跑贏大市，否則買指數就好。評分裡「一星期相對 SPY」權重最高；可選開關「跑贏 SPY」要求近約 5 個與 20 個交易日收市對收市總回報減 SPY 皆為正，兩者同時符合才留下。",
  },
  {
    title: "找出領導板塊（資金喜好的那類）",
    body: "通過名單按細分板塊家數排熱力圖，只顯示頭十位。先看哪個板塊最多 Stage 2 股份，再在板塊內挑評分／相對強度較高的標的。",
  },
  {
    title: "距離 200 天線較近，升勢相對早期",
    body: "評分把「與 200 天線的距離」放在首位之一：離線愈近分數愈高，距離過遠（升勢已走遠）分數會被壓低，方便優先看較早期的升勢。",
  },
  {
    title: "價格剛好落在支持位",
    body: "可選開關「收市近支持」：最新收市落在結構支持區內。止蝕可放支持位下面，向上機率相對較高。支持區以日線結構估計（清晰擺動低點＋近約 20／60 日區間低點，並把 10／20／50／150／200 天線計入匯合；須至少兩次觸及才標出）。圖表只畫中軸虛線；篩選用中軸 ±0.5×ATR 區。優先取較接近中軸、且收市在中軸上方的支持。篩選與圖表共用同一套定義。",
  },
]

export function StrategyPage() {
  useEffect(() => {
    document.title = "美股篩選器 · 策略說明"
  }, [])

  return (
    <article className="mx-auto max-w-3xl space-y-8 pb-8">
      <header>
        <p className="text-xs tracking-[0.22em] text-muted-foreground">美股篩選器</p>
        <h1 className="mt-1 font-heading text-4xl font-semibold">策略說明</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          本站按以下六步篩選美股：先鎖定 Stage 2，再收緊市值與流動性、相對強度、領導板塊、升勢早期程度，以及是否靠近支持位。
        </p>
      </header>

      <section className="space-y-4 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">篩選思路（六步）</h2>
        <ol className="space-y-4">
          {STEPS.map((step, index) => (
            <li key={step.title} className="rounded-lg border border-border bg-secondary/20 px-4 py-3">
              <p className="font-medium">
                <span className="text-muted-foreground">{index + 1}.</span> {step.title}
              </p>
              <p className="mt-2 text-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-2xl">評分</h2>
        <p className="text-sm leading-relaxed">
          通過硬性條件之後，評分只決定先後，滿分 100。一隻股份可以通過均線堆疊但近一星期落後 SPY，評分就會偏低。
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
          <li>跑贏 SPY：近約 5 個與 20 個交易日收市對收市總回報減 SPY 皆為正（兩者同時符合）。</li>
          <li>
            收市近支持：見上文第 6 步。全量更新時會重算，規則版本變更時亦會用已存日線重填此欄。
          </li>
          <li>
            近一星期升幅：股份本身近約 5 個交易日收市對收市升幅 ≥ 你輸入的 X%（網址參數
            <code className="mx-1 rounded bg-secondary px-1">gain1w</code>
            ；預設 5）。唔係相對 SPY。
          </li>
        </ul>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">數據與股票池</h2>
        <p>
          成份來自 Nasdaq Trader 免費符號目錄（nasdaqlisted／otherlisted），保留美股普通股，剔除
          ETF、ETN、NextShares、ADR／ADS、測試股、權證、單位、優先股等明顯標記。下載失敗時改用上一次成功存下來的名單。
        </p>
        <p>
          行情來自 Yahoo Finance 的公開圖表與報價接口，不需要 API 金鑰。K 線和均線用拆股還原價，成交額用未還原收市價乘成交量。免費數據可能延遲、缺漏，或在盤中改寫最後一根日線。結果會寫入本機
          SQLite；全量更新按批次下載，預設 12 小時內不重複全量下載；手動更新另有約五分鐘的冷卻。
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
