# Deploy 階律 / US Stock Filter on Render (free)

One **web** service builds the Vite frontend into the FastAPI image and serves both on `$PORT`.

## Notes

- **Cache is ephemeral on the free plan.** `KAI_LUT_CACHE=/app/cache` lives on the instance filesystem. After sleep, redeploy, or restart, SQLite cache is gone and a refresh rebuilds it. That is expected; no disk is attached.
- Free web services **spin down after inactivity** (cold start on the next request).
- Local `docker compose` is unchanged (`backend/` + `frontend/` images; nginx proxies `/api`).

## Steps

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
