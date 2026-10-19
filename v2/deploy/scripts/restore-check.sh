#!/usr/bin/env bash
# Restore a dump into a scratch database and run the ledger integrity checks against it.
# Usage (from the compose directory): deploy/scripts/restore-check.sh backups/db/bookkeeper-<stamp>.dump
# Weekly cron: 0 4 * * 1 cd /opt/bookkeeper && deploy/scripts/restore-check.sh "$(ls -1t backups/db/*.dump | head -1)"
set -euo pipefail
# .env is compose syntax, not shell: read the one value needed instead of sourcing it.
owner_password="${BK_OWNER_DB_PASSWORD:-$(sed -n 's/^BK_OWNER_DB_PASSWORD=//p' .env)}"

dump="${1:?usage: restore-check.sh <dump file>}"
scratch="bookkeeper_restore_check"
(cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256")
docker compose exec -T db dropdb -U bk_owner --if-exists "$scratch"
docker compose exec -T db createdb -U bk_owner "$scratch"
trap 'docker compose exec -T db dropdb -U bk_owner --if-exists "$scratch"' EXIT
docker compose exec -T db pg_restore -U bk_owner -d "$scratch" --no-owner --exit-on-error < "$dump"
docker compose run --rm -T --no-deps \
  -e BK_DATABASE_URL="postgresql+psycopg://bk_owner:${owner_password:?BK_OWNER_DB_PASSWORD missing}@db:5432/$scratch" \
  api bookkeeper run-checks --codes trial_balance_zero,entries_balanced,hash_chain
echo "restore check ok: $dump"
