#!/bin/sh
# Prove a backup can be restored (PROJECT-REGISTER No. 199, TK-001).
#
#   sh deploy/restore-check.sh                      # the newest backup
#   sh deploy/restore-check.sh ../CSP_Backups/cspdocmaker-backup-2026-11-24-0230.dump
#
# Restores the backup into a THROWAWAY database container (its own, removed
# at the end) — never the live or test-copy database — then counts the rows
# of the main tables so you can compare them with the live app.

set -eu
cd "$(dirname "$0")/.."
DIR="${BACKUP_HOST:-../CSP_Backups}"
FILE="${1:-$(ls -1t "$DIR"/cspdocmaker-backup-*.dump 2>/dev/null | head -1)}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "No backup found (looked in $DIR)."; exit 1; }
FILE=$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")
NAME="cspdocmaker-restore-check-$$"

echo "Restoring $FILE into a throwaway database ($NAME)..."
docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=check -e POSTGRES_DB=check \
  -v "$FILE":/backup.dump:ro postgres:16-alpine >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT
i=0
until docker exec "$NAME" pg_isready -U postgres -d check >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -lt 60 ] || { echo "The throwaway database did not start."; exit 1; }
  sleep 1
done
sleep 2
# The file goes in on stdin, so no folder has to be shared with Docker.
docker exec -i "$NAME" pg_restore -U postgres -d check --no-owner --exit-on-error < "$FILE"
echo "Restored. Rows in the main tables:"
docker exec "$NAME" psql -U postgres -d check -At -F ' : ' -c "
  select 'csp_records', count(*) from csp_records union all
  select 'stored_documents', count(*) from stored_documents union all
  select 'whatsapp_messages', count(*) from whatsapp_messages union all
  select 'email_messages', count(*) from email_messages union all
  select 'data_requests', count(*) from data_requests union all
  select 'audit_logs', count(*) from audit_logs"
echo "RESTORE CHECK PASSED: $(basename "$FILE") can be restored."
