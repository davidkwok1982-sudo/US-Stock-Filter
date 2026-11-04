import { useEffect } from "react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

const SCORE_ROWS = [
  ["與200天線的距離", "15", "高於 0–30% 得 15；30–60% 得 9；超過 60% 得 4。未站上得 0。"],
  ["站上50天線", "15", "現價高於50天線得 15，否則 0。"],
  ["50天線向上", "10", "50天線較約20個交易日前上升。"],
  ["200天線向上", "10", "200天線較約20個交易日前上升。"],
  ["貼近52週高位", "15", "距高位 8% 內得 15；15% 內得 12；25% 內得 8；40% 內得 3。"],
  ["六個月相對 SPY", "20", "落後 20 個百分點或更多為 0，持平約 8，領先 30 個百分點或更多為 20。"],
  ["流動性", "10", "日均成交額 3,000 萬美元約 4 分，大約八倍（2.4 億美元）封頂 10 分。"],
  ["貝他區間", "5", "1.0–1.6 得 5；1.6–2.2 得 4；更高得 2。低於 1 得 0。"],
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
          美股篩選器把公開文章裡的第二階段條件，做成一個可重算的美股篩選。它是教育近似，不是任何專有交易系統，也不是投資建議。
        </p>
      </header>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">這頁在做甚麼</h2>
        <p>
          股價相對 200 天線的位置可分成四個階段。第一階段是底部整固，均線走平。第二階段是上升趨勢，股價站上並通常帶動向上的長期均線。第三階段見頂派發。第四階段跌破長期均線。
        </p>
        <p>
          公開流傳的第二階段篩選，會再加上市值、流動性和貝他，讓名單集中在夠大、夠活躍、波幅不低於大市的美股。本站把這些條件寫成可檢查的數字，並用評分在通過名單裡排序。
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-2xl">硬性條件</h2>
        <p className="text-sm text-muted-foreground">四項都要通過，才會計入「通過家數」，也才會出現在預設表格。</p>
        <ol className="space-y-3 text-sm leading-relaxed">
          <li>
            <span className="font-medium">1. 股價高於 200 天線。</span>
            用拆股還原後的收市價計算簡單移動平均。現價取 Yahoo 報價；若與最後一根日線差太遠，改用日線收市價。
          </li>
          <li>
            <span className="font-medium">2. 市值逾 20 億美元。</span>
            取 Yahoo 報價的市值。沒有市值就不會放行。
          </li>
          <li>
            <span className="font-medium">3. 日均成交額約 3,000 萬美元或以上。</span>
            優先用過去 63 個交易日的未還原收市價乘成交量再取平均。日線不足，則用三個月平均成交量乘現價，並在個股頁註明。公開文章亦有「每月成交額逾 9 億美元」的講法，大約等於每日 3,000 萬美元。
          </li>
          <li>
            <span className="font-medium">4. 貝他不低於 1。</span>
            優先用 Yahoo Finance 公布的貝他。該欄經常是空的，空則改以過去約 90 個重疊交易日的日回報對 SPY 做迴歸，表內會標「90日」。觀測少於 60 日就列為未明，不會蒙混過關。
          </li>
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-2xl">評分</h2>
        <p className="text-sm leading-relaxed">
          通過硬性條件之後，評分只決定先後，滿分 100。一隻股份可以站上 200 天線但遠離高位、50 天線向下，評分就會偏低。
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
        <p>這些開關預設大多關掉。打開之後只會縮小表格，不會改寫頂部的通過家數。</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>高於 50 天線。</li>
          <li>50 天線與 200 天線過去約一個月都向上。</li>
          <li>現價距 52 週高位 25% 以內。距 15% 以內會在評分裡拿更高分。</li>
          <li>六個月回報跑贏 SPY。三個月差距會一併顯示，但不單獨做開關。</li>
          <li>收市近支持：以日線擺動低點（兩次以上觸及，或一次清晰擺動）估計支持；最新收市落在該位約 1% 內（高於約 1.2% 或以內、輕微刺穿約 1% 內仍可；明顯低於約 1.8% 則否），優先取最接近且不大於收市價的支持。屬教育約數；全量更新時會重算，規則版本變更時亦會用已存日線重填此欄。</li>
          <li>排除場外及微盤：股價低於 5 美元、市值少於 3 億美元，或交易所屬場外。本宇宙本來就少有這類股份，20 億市值門檻已經先擋掉微盤。</li>
        </ul>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">廣度提示</h2>
        <p>
          通過家數達 200 或以上，標成廣度偏多；少於 100，標成宜審慎；介乎其中則為中性。這組數字來自公開文章的經驗講法。本站只數標普 500、標普中型 400 和納指 100 的合併名單，不是全美所有股票，所以應把它讀成「這批流動性較好的股份裡，有多少隻同時站上長期均線、夠大、夠活躍、貝他不低」，而不是整個美股市場的寬度。
        </p>
      </section>

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">數據與宇宙</h2>
        <p>
          成份來自維基百科的標普 500、標普中型 400 與納斯達克 100 名單，重疊代號只留一隻，並記下它屬哪些指數。代號裡的點會改成 Yahoo 用的連字號，例如 BRK.B 變成 BRK-B。維基若暫時打不開，就用上一次成功存下來的名單。
        </p>
        <p>
          行情來自 Yahoo Finance 的公開圖表與報價接口，不需要 API 金鑰。K 線和均線用拆股還原價，成交額用未還原收市價乘成交量。免費數據可能延遲、缺漏，或在盤中改寫最後一根日線。結果會寫入本機 SQLite，預設 12 小時內不重複全量下載；手動更新另有約五分鐘的冷卻。
        </p>
        <p>個股頁的行業、市盈率和收入增長來自 Yahoo 的免費公司摘要，季報數字可能落後。沒有就不硬填。</p>
      </section>

      <section id="upcoming" className="space-y-3">
        <h2 className="font-heading text-2xl">即將推出</h2>
        <p className="text-sm text-muted-foreground">介面和 API 已留了策略編號。下面兩套尚未計算，打開篩選不會假裝有結果。</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <Badge variant="outline">即將推出</Badge>
              <CardTitle className="font-heading text-xl">趨勢模板</CardTitle>
            </CardHeader>
            <CardContent className="text-sm leading-relaxed text-muted-foreground">
              預留：股價高於 150 及 200 天線、150 天線高於 200 天線、距 52 週低位與高位的距離，以及相對強度排名。接入時會做成另一個策略分頁，而不是改掉第二階段的硬性條件。
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <Badge variant="outline">即將推出</Badge>
              <CardTitle className="font-heading text-xl">成長股法則</CardTitle>
            </CardHeader>
            <CardContent className="text-sm leading-relaxed text-muted-foreground">
              預留：盈利與銷售增長、接近新高、領先股與需求等公開框架。基本因素目前只在個股頁作短註，尚未構成篩選。
            </CardContent>
          </Card>
        </div>
      </section>

      <Separator />

      <section className="space-y-3 text-sm leading-relaxed">
        <h2 className="font-heading text-2xl">免責</h2>
        <p className="font-medium">短線觀察，非投資建議。</p>
        <p>
          本站按公開流傳的篩選條件作教育近似，與任何商業篩選器或其作者無關聯，亦未獲授權。計算結果可能因免費數據、貝他窗口和指數成份變動而與其他工具不同。不要單憑這張表決定買賣。
        </p>
        <p>
          <Link to="/" className="underline underline-offset-4">
            返回篩選結果
          </Link>
        </p>
      </section>
    </article>
  )
}
