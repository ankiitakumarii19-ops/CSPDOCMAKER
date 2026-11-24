#!/bin/sh
# One safe update of the app on the server (PROJECT-REGISTER No. 199,
# Stage 0, task TK-003). Run in the app folder, as the folder's owner:
#
#   sh deploy/update.sh test     # the test copy first (/csp-docmaker-test)
#   sh deploy/update.sh live     # then the live app
#
# 1. backup of the database (before anything changes)
# 2. git pull (only a fast-forward)
# 3. build the new version
# 4. the golden cases run ON THE NEW VERSION, in a throwaway database, with
#    nothing able to send (TEST_COPY=true). One failure = STOP: the running
#    app is left exactly as it was.
# 5. start the new version, then check it answers.

set -eu
cd "$(dirname "$0")/.."

case "${1:-}" in
  live) C="docker compose -f docker-compose.prod.yml --env-file deploy/.env.production"
        GOLDEN_DB=cspdocmaker_golden; NAME=cspdocmaker ;;
  test) C="docker compose -p cspdocmaker-test -f docker-compose.prod.yml --env-file deploy/.env.test"
        GOLDEN_DB=cspdocmaker_test_golden; NAME=cspdocmaker-test ;;
  *) echo "Say which copy: sh deploy/update.sh test   or   sh deploy/update.sh live"; exit 1 ;;
esac
BACKUPS="$(grep -E '^BACKUP_HOST=' "$( [ "$1" = live ] && echo deploy/.env.production || echo deploy/.env.test )" 2>/dev/null | cut -d= -f2-)"
BACKUPS="${BACKUPS:-$( [ "$1" = live ] && echo ../CSP_Backups || echo ../CSP_Backups_test )}"
mkdir -p "$BACKUPS"
before=$(git rev-parse --short HEAD)
stamp=$(date -u +%Y-%m-%d-%H%M)

echo "== 1/5 Backup of the $1 database"
file="$BACKUPS/$NAME-backup-$stamp-before-update.dump"
$C exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" --no-owner --format=custom "$POSTGRES_DB"' > "$file"
[ -s "$file" ] || { echo "STOPPED: the backup is empty. Nothing was changed."; rm -f "$file"; exit 1; }
echo "   saved $file ($(du -h "$file" | cut -f1))"

echo "== 2/5 git pull (was $before)"
git pull --ff-only
after=$(git rev-parse --short HEAD)
echo "   now $after"

echo "== 3/5 Build"
$C build api frontend

echo "== 4/5 Golden cases on the new version"
set +e
out=$($C run --rm --no-deps -T -e TEST_COPY=true -e EMAILS_PAUSED=true \
      -e TEST_DATABASE_NAME="$GOLDEN_DB" api \
      python -m pytest -q -p no:cacheprovider tests/test_golden_cases.py 2>&1)
status=$?
set -e
$C exec -T postgres sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $GOLDEN_DB" >/dev/null 2>&1 || true
summary=$(echo "$out" | tail -1)
if [ $status -ne 0 ] || echo "$summary" | grep -q "skipped"; then
  echo "$out" | grep -E "^(FAILED|ERROR)" | head -20
  echo "   $summary"
  echo "STOPPED: a golden case failed (or could not run) on $after."
  echo "The running app was NOT changed. To put the code back:  git checkout $before"
  exit 1
fi
echo "   $summary"

echo "== 5/5 Start the new version"
$C up -d
i=0
until $C exec -T api curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 40 ]; then
    echo "The new version does not answer after 2 minutes. Look at:  $C logs --tail 100 api"
    echo "To go back: git checkout $before && $C up -d --build   (backup: $file)"
    exit 1
  fi
  sleep 3
done
$C ps
echo "DONE: $1 updated $before -> $after; golden cases passed; backup $file"
