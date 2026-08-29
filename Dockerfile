FROM debian:bookworm-slim AS sqlite-builder

ARG SQLITE_ARCHIVE=sqlite-autoconf-3530400
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates wget \
    && wget --quiet "https://www.sqlite.org/2026/${SQLITE_ARCHIVE}.tar.gz" \
    && tar -xzf "${SQLITE_ARCHIVE}.tar.gz" \
    && cd "${SQLITE_ARCHIVE}" \
    && CPPFLAGS="-DSQLITE_ENABLE_FTS5" ./configure --prefix=/usr/local --disable-static \
    && make -j2 \
    && make install \
    && ldconfig \
    && sqlite_version="$(/usr/local/bin/sqlite3 ':memory:' 'SELECT sqlite_version();')" \
    && dpkg --compare-versions "${sqlite_version}" ge "3.51.3" \
    && test "$(/usr/local/bin/sqlite3 ':memory:' \
        "SELECT sqlite_compileoption_used('ENABLE_FTS5');")" = "1" \
    && /usr/local/bin/sqlite3 ':memory:' \
        'CREATE VIRTUAL TABLE fts5_build_probe USING fts5(content);'

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

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglib2.0-0 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=sqlite-builder /usr/local/lib/libsqlite3.so* /usr/local/lib/
RUN ldconfig \
    && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3); connection = sqlite3.connect(':memory:'); assert connection.execute(\"SELECT sqlite_compileoption_used('ENABLE_FTS5')\").fetchone() == (1,); connection.execute('CREATE VIRTUAL TABLE fts5_runtime_probe USING fts5(content)')"

WORKDIR /app
COPY pyproject.toml requirements.runtime.lock README.md alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY --from=frontend-builder /frontend/dist ./frontend/dist
RUN pip install --no-cache-dir --requirement requirements.runtime.lock \
    && pip install --no-cache-dir --no-deps . \
    && cd /tmp \
    && python -c "import cv2, rapidocr; from app.main import app; from importlib.resources import files; assert files('app').joinpath('defaults', 'AGENTS.md').read_text(encoding='utf-8')" \
    && useradd --create-home --uid 10001 ledger \
    && mkdir -p /app/data /app/backups \
    && chown -R ledger:ledger /app

USER ledger
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
