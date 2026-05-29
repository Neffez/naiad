# Stage 1: Frontend build (Vite → static assets, relative base for HA ingress).
FROM node:22-alpine AS frontend-build
WORKDIR /app/src/frontend
COPY src/frontend/package.json src/frontend/package-lock.json ./
# --legacy-peer-deps: the toolchain pins a newer TypeScript than some lint peers
# declare; the build itself (tsc + vite) is clean with it.
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY src/frontend/ ./
# vite `outDir` is ../../static → builds to /app/static
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

# Mirror the repo layout so pyproject's readme (../../README.md) resolves, and the
# package is present *before* the install. Editable install keeps `naiad` importable
# from /app/src/backend while main.py finds the sibling ./static at runtime.
COPY README.md ./README.md
COPY src/backend ./src/backend
RUN pip install --no-cache-dir -e ./src/backend

COPY --from=frontend-build /app/static/ ./src/backend/static/

VOLUME ["/data"]

ENV NAIAD_CONFIG=/data/config.yaml
ENV NAIAD_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"

CMD ["uvicorn", "naiad.main:app", "--host", "0.0.0.0", "--port", "8080"]
