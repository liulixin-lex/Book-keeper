FROM debian:bookworm-slim AS sqlite-builder

ARG SQLITE_ARCHIVE=sqlite-autoconf-3530400
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates wget \
    && wget --quiet "https://www.sqlite.org/2026/${SQLITE_ARCHIVE}.tar.gz" \
    && tar -xzf "${SQLITE_ARCHIVE}.tar.gz" \
    && cd "${SQLITE_ARCHIVE}" \
    && ./configure --prefix=/usr/local --disable-static \
    && make -j2 \
    && make install

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/usr/local/lib

COPY --from=sqlite-builder /usr/local/lib/libsqlite3.so* /usr/local/lib/
RUN ldconfig \
    && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3)"

WORKDIR /app
COPY pyproject.toml requirements.lock README.md alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY --from=frontend-builder /frontend/dist ./frontend/dist
RUN pip install --no-cache-dir --requirement requirements.lock \
    && pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 ledger \
    && mkdir -p /app/data /app/backups \
    && chown -R ledger:ledger /app

USER ledger
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
