# syntax=docker/dockerfile:1.7
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./web

RUN useradd --system --uid 10001 --home /app bk \
    && mkdir -p /data \
    && chown bk:bk /data

USER bk
ENV PATH=/app/.venv/bin:$PATH \
    BK_DATA_DIR=/data \
    BK_WEB_DIR=/app/web \
    BK_ENVIRONMENT=production

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["bookkeeper", "healthcheck"]
CMD ["bookkeeper", "serve", "--host", "0.0.0.0", "--port", "8000"]
