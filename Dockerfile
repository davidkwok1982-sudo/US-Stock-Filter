# syntax=docker/dockerfile:1
# Single free-tier Render web service: Vite SPA + FastAPI on $PORT.
# Local docker-compose still uses backend/Dockerfile + frontend/Dockerfile.

FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/data ./data
COPY --from=frontend /frontend/dist ./static

ENV KAI_LUT_CACHE=/app/cache \
    KAI_LUT_STATIC=/app/static \
    KAI_LUT_TTL_HOURS=12 \
    PORT=10000

RUN mkdir -p /app/cache

EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
