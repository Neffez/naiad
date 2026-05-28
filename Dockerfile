# Stage 1: Frontend build (added in Phase 4)
# Placeholder produces an empty static dir so the image builds now.
FROM node:20-alpine AS frontend-build
WORKDIR /app
RUN mkdir -p dist && \
    echo '<!DOCTYPE html><html><head><title>Naiad</title></head><body><h1>Naiad</h1><p>UI not yet built.</p></body></html>' \
    > dist/index.html

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY src/backend/pyproject.toml ./
RUN pip install --no-cache-dir -e "."

COPY src/backend/naiad/ ./naiad/

COPY --from=frontend-build /app/dist/ ./static/

VOLUME ["/data"]

ENV NAIAD_CONFIG=/data/config.yaml
ENV NAIAD_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"

CMD ["uvicorn", "naiad.main:app", "--host", "0.0.0.0", "--port", "8080"]
