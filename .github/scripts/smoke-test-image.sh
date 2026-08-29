#!/usr/bin/env bash
set -Eeuo pipefail

: "${IMAGE:?IMAGE must name the locally loaded image to test}"

suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$"
volume="book-keeper-smoke-${suffix}"
api_container="book-keeper-api-${suffix}"
worker_container="book-keeper-worker-${suffix}"

cleanup() {
  docker rm --force "${worker_container}" "${api_container}" >/dev/null 2>&1 || true
  docker volume rm --force "${volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "${volume}" >/dev/null

docker run --rm --interactive --workdir /tmp "${IMAGE}" python - <<'PY'
import sqlite3
from importlib.resources import files

import cv2
import rapidocr
from app.main import app

assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version
with sqlite3.connect(":memory:") as connection:
    enabled = connection.execute(
        "SELECT sqlite_compileoption_used('ENABLE_FTS5')"
    ).fetchone()
    assert enabled == (1,), enabled
    connection.execute("CREATE VIRTUAL TABLE fts5_smoke_probe USING fts5(content)")

assert app is not None
assert cv2.__version__
assert rapidocr.__name__ == "rapidocr"
assert files("app").joinpath("defaults", "AGENTS.md").read_text(encoding="utf-8")
print(f"SQLite {sqlite3.sqlite_version}; FTS5 enabled; OpenCV {cv2.__version__}")
PY

docker run --rm --workdir /tmp "${IMAGE}" sh -ec '
  cv2_binary="$(python -c '\''import cv2; from pathlib import Path; print(next(Path(cv2.__file__).parent.glob("*.so")))'\'')"
  ldd "${cv2_binary}" | tee /tmp/cv2-ldd.txt
  if grep --quiet "not found" /tmp/cv2-ldd.txt; then
    exit 1
  fi
'

docker run --rm \
  --env PYTHONPATH= \
  --env DATABASE_URL=sqlite:////app/data/ledger.db \
  --volume "${volume}:/app/data" \
  "${IMAGE}" ledger-admin init-db

docker run --detach \
  --name "${api_container}" \
  --env PYTHONPATH= \
  --env APP_ENV=production \
  --env APP_SECRET_KEY=container-smoke-test-secret \
  --env DATABASE_URL=sqlite:////app/data/ledger.db \
  --env SESSION_COOKIE_SECURE=true \
  --volume "${volume}:/app/data" \
  "${IMAGE}" >/dev/null

api_ready=false
for _ in $(seq 1 30); do
  if [ "$(docker inspect --format '{{.State.Running}}' "${api_container}")" != "true" ]; then
    docker logs "${api_container}"
    exit 1
  fi
  if docker exec "${api_container}" python -c \
    "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); assert response.status == 200" \
    >/dev/null 2>&1; then
    api_ready=true
    break
  fi
  sleep 2
done

if [ "${api_ready}" != "true" ]; then
  docker logs "${api_container}"
  exit 1
fi

docker run --detach \
  --name "${worker_container}" \
  --env PYTHONPATH= \
  --env APP_ENV=production \
  --env APP_SECRET_KEY=container-smoke-test-secret \
  --env DATABASE_URL=sqlite:////app/data/ledger.db \
  --volume "${volume}:/app/data" \
  "${IMAGE}" python -m app.worker >/dev/null

sleep 10
if [ "$(docker inspect --format '{{.State.Running}}' "${worker_container}")" != "true" ]; then
  docker logs "${worker_container}"
  exit 1
fi

docker logs "${api_container}"
docker logs "${worker_container}"
