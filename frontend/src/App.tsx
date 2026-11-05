import { Navigate, Route, Routes } from "react-router-dom"

import { Layout } from "@/components/layout.tsx"
import { ScreenPage } from "@/pages/screen-page.tsx"
import { StockPage, StockPicker } from "@/pages/stock-page.tsx"
import { StrategyPage } from "@/pages/strategy-page.tsx"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ScreenPage />} />
        <Route path="stock" element={<StockPicker />} />
        <Route path="stock/:symbol" element={<StockPage />} />
        <Route path="strategy" element={<StrategyPage />} />
        <Route path="hk" element={<ScreenPage />} />
        <Route path="hk/stock" element={<StockPicker />} />
        <Route path="hk/stock/:symbol" element={<StockPage />} />
        <Route path="hk/strategy" element={<StrategyPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
