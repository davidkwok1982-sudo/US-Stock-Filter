# 階律

美股第二階段觀察台。按公開描述的 Stage 2／第二階段條件篩選全美上市普通股（已剔除 ADR 與 ETF），並在個股頁畫出蠟燭圖、50／150／200 天線和近似支持／阻力。

介面為繁體中文（香港用語，升紅跌綠）。

趨勢模板與成長股法則只預留了策略位置，尚未計算。

## 本地啟動

只需要一個指令。第一次會建立 Python 虛擬環墉並安裝前端依賴。

```bash
./start.sh
```

- 介面：<http://127.0.0.1:43123>
- API：<http://127.0.0.1:43124>

首次打開會向 Yahoo Finance 分批下載數千隻股份的日線與市值，需時較長，之後寫入 `backend/cache/market.sqlite`。預設 12 小時內不會再全量下載。

也可以分開啟動：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 43124

cd frontend && npm install && npm run dev
```

### Docker Compose

```bash
docker compose up --build
```

瀏覽器打開 <http://127.0.0.1:43123>。快取放在名為 `kailut-cache` 的 volume。

## 環境變數

不需要 API 金鑰。

| 變數 | 預設 | 作用 |
| --- | --- | --- |
| `KAI_LUT_TTL_HOURS` | `12` | 快取過期前不自動全量更新 |
| `KAI_LUT_CACHE` | `backend/cache` | SQLite 目錄 |
| `KAI_LUT_WORKERS` | `10` | 下載日線的並行數 |
| `KAI_LUT_CHUNK` | `250` | 全量更新每批符號數（避免一次載入過多） |
| `KAI_LUT_COOLDOWN` | `300` | 手動「重新整理」的最短間隔（秒） |
| `KAI_LUT_LIMIT` | 不設 | 只取宇宙前 N 隻，方便除錯 |

## 篩選在算甚麼

硬性條件（預設表格與「通過家數」）：

1. 現價＞50 天線＞150 天線＞200 天線
2. 50／150／200 天線過去約一個月都向上
3. 市值逾 20 億美元

可選收緊（不改寫通過家數）：近一星期跑贏 SPY、收市近支持。

通過家數達 200 或以上標為廣度偏多，少於 100 標為宜審慎。熱力圖只顯示細分版塊家數頭十位。

細節與評分表見站內「策略說明」。

## 數據與限制

- 來源是 Yahoo Finance 公開圖表、報價與公司摘要，無需金鑰。若 Yahoo 暫時拒絕連線，更新會失敗並保留上一份快取。
- K 線與均線用拆股還原價；成交額用未還原收市價 × 成交量。
- 符號目錄來自 Nasdaq Trader（nasdaqlisted／otherlisted），成功後寫進 `backend/data/universe.json`，下載失敗時用這份名單。已剔除 ETF／ETN／ADR／ADS／權證／單位／優先股等。
- 個股的行業、市盈率、收入增長視 Yahoo 是否有提供，沒有就不填。

## 測試

```bash
source .venv/bin/activate
cd backend && PYTHONPATH=. python -m pytest tests -q
cd ../frontend && npx tsc -b --noEmit
```

## 之後加策略

`backend/app/strategies.py` 登記策略編號。`GET /api/screen?strategy=minervini`（內部策略 id，即將推出）目前回 501。第二階段的計算在 `backend/app/evaluate.py` 與 `metrics.py`。新策略可以沿用同一套 Yahoo 快取，另寫一個 `evaluate`，再在前端策略分頁接上。
