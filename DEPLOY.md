# Deploy 階律 / US Stock Filter

## FastAPI Cloud (Hobby — no Docker)

Deploy root is **`backend/`**. FastAPI Cloud does not run `npm`; build the SPA first and upload `dist/`.

### One-time setup

```bash
cd frontend
npm ci
cd ../backend
python3 -m venv .venv   # or reuse repo .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install "fastapi[standard]"
fastapi login               # opens browser; interactive auth
```

### Every deploy

```bash
# 1) Build frontend into backend/dist (deploy expects dist next to app/)
cd /path/to/US-Stock-Filter/frontend
npm ci && npm run build
rm -rf ../backend/dist && cp -R dist ../backend/dist

# 2) Deploy from backend/
cd ../backend
fastapi deploy
```

- `backend/pyproject.toml` sets `requires-python >=3.12`, deps (`fastapi[standard]`, …), and `[tool.fastapi] entrypoint = "app.main:app"`.
- `backend/.fastapicloudignore` contains `!dist/` so the gitignored build is still uploaded.
- The app serves the SPA with `app.frontend("/", directory=…, fallback="index.html")` when available; otherwise `StaticFiles`.

Optional env (CLI or dashboard): `KAI_LUT_TTL_HOURS`, `KAI_LUT_CACHE`. Static dir defaults to `dist/` (or `KAI_LUT_STATIC`).

Do not commit `backend/dist/`; rebuild before each `fastapi deploy`.

Health: `GET /api/health`

---

## Render (free, Docker)

One **web** service builds the Vite frontend into the FastAPI image and serves both on `$PORT`.

### Notes

- **Cache is ephemeral on the free plan.** `KAI_LUT_CACHE=/app/cache` lives on the instance filesystem. After sleep, redeploy, or restart, SQLite cache is gone and a refresh rebuilds it. That is expected; no disk is attached.
- Free web services **spin down after inactivity** (cold start on the next request).
- Local `docker compose` is unchanged (`backend/` + `frontend/` images; nginx proxies `/api`). Root `Dockerfile` still copies the SPA into `/app/static` (`KAI_LUT_STATIC`).

### Steps

1. Push this repo to GitHub/GitLab/Bitbucket.
2. Validate: `render blueprints validate render.yaml`
3. Create via Blueprint deeplink, or:

```bash
render services create \
  --name us-stock-filter \
  --type web_service \
  --runtime docker \
  --plan free \
  --region singapore \
  --repo <GITHUB_REPO_HTTPS_URL> \
  --branch main \
  --health-check-path /api/health \
  --env-var KAI_LUT_TTL_HOURS=12 \
  --env-var KAI_LUT_CACHE=/app/cache \
  --confirm \
  --output json
```

Health: `GET /api/health`


---

## 港股篩選器（同站）

- 前端路由：`/hk`、`/hk/stock/:symbol`、`/hk/strategy`（頂部 美股／港股 切換）。
- API：`GET /api/hk/screen`、`POST /api/hk/refresh`、`GET /api/hk/stock/{symbol}`、`GET /api/hk/stock/{symbol}/profile`。
- 股票池：HKEX List of Securities → `XXXX.HK`；快取 `universe_hk.json` + `market_hk.sqlite`（與美股分開）。
- 繁中簡稱：HKEXnews `activestock_sehk_c.json` → `nameZh`（快取 `hk_names_zh.json`）。`/api/hk/screen` 在回應時合併名稱，舊快照無需全量重篩亦可顯示；刷新股票池時會一併更新名稱圖。
- 基準：恆生指數 `^HSI`；軟籌碼「跑贏恆指」需約 5 日與 20 日 RS 皆為正。
- 市值硬門檻：**HK$100 億**（= 10_000_000_000；Yahoo `.HK` marketCap 通常為港元）。
- Hobby 部署磁碟為臨時：港股冷啟動**不會**自動全量刷新，請按頁面「重新整理」或 `POST /api/hk/refresh`。首次下載全市場需時較長。
