#!/usr/bin/env bash
# Daily backup: PostgreSQL custom-format dump + attachment store snapshot, verified, with tiered retention.
# Run on the host from the compose directory, e.g. cron: 0 3 * * * cd /opt/bookkeeper && deploy/scripts/backup.sh
set -euo pipefail   # Linux host (GNU date)

BACKUP_DIR="${BK_BACKUP_DIR:-/opt/bookkeeper/backups}"
KEEP_DAILY="${BK_KEEP_DAILY:-14}"
KEEP_WEEKLY="${BK_KEEP_WEEKLY:-8}"
KEEP_MONTHLY="${BK_KEEP_MONTHLY:-12}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"

dump="$BACKUP_DIR/db/bookkeeper-$STAMP.dump"
docker compose exec -T db pg_dump -U bk_owner -d bookkeeper -Fc > "$dump.partial"
docker compose exec -T db pg_restore --list < "$dump.partial" > /dev/null   # readable archive?
mv "$dump.partial" "$dump"
(cd "$BACKUP_DIR/db" && sha256sum "$(basename "$dump")" > "$(basename "$dump").sha256")

# Attachments are content-addressed and never rewritten: hard-link snapshot of the data volume.
data_volume="$(docker volume inspect -f '{{ .Mountpoint }}' "${BK_DATA_VOLUME:-bookkeeper_data}")"
latest="$BACKUP_DIR/files/latest"
snapshot="$BACKUP_DIR/files/$STAMP"
if [ -d "$latest" ]; then
  rsync -a --delete --link-dest="$latest" "$data_volume/" "$snapshot/"
else
  rsync -a "$data_volume/" "$snapshot/"
fi
ln -sfn "$snapshot" "$latest"

# Retention: newest $KEEP_DAILY dumps, plus the newest dump of each of the last
# $KEEP_WEEKLY ISO weeks and $KEEP_MONTHLY months. File snapshots keep $KEEP_DAILY.
keep="$(mktemp)"
trap 'rm -f "$keep"' EXIT
declare -A weeks=() months=()
n=0
while read -r f; do
  n=$((n + 1))
  day="$(basename "$f" .dump)"; day="${day#bookkeeper-}"; day="${day:0:8}"
  week="$(date -u -d "$day" +%G%V)"; month="${day:0:6}"
  if [ "$n" -le "$KEEP_DAILY" ]; then echo "$f" >> "$keep"; fi
  if [ -z "${weeks[$week]:-}" ] && [ "${#weeks[@]}" -lt "$KEEP_WEEKLY" ]; then weeks[$week]=1; echo "$f" >> "$keep"; fi
  if [ -z "${months[$month]:-}" ] && [ "${#months[@]}" -lt "$KEEP_MONTHLY" ]; then months[$month]=1; echo "$f" >> "$keep"; fi
done < <(ls -1t "$BACKUP_DIR"/db/*.dump)
{ ls -1 "$BACKUP_DIR"/db/*.dump | grep -vxFf "$keep" || true; } | while read -r old; do rm -f "$old" "$old.sha256"; done
ls -1dt "$BACKUP_DIR"/files/2* | tail -n +"$((KEEP_DAILY + 1))" | xargs -r rm -rf

echo "backup ok: $dump ($(du -h "$dump" | cut -f1))"
