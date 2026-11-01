#!/usr/bin/env bash
# Start the API (43124) and the Traditional Chinese UI (43123).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r backend/requirements.txt

if [[ ! -d frontend/node_modules ]]; then
  npm install --prefix frontend
fi

mkdir -p backend/cache

python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 43124 &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ready=0
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:43124/api/health" >/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API 未能啟動" >&2
    exit 1
  fi
  sleep 0.2
done
if [[ "$ready" -ne 1 ]]; then
  echo "API 未能在時限內回應" >&2
  exit 1
fi

echo "介面 http://127.0.0.1:43123  ·  API http://127.0.0.1:43124"
exec npm run dev --prefix frontend
