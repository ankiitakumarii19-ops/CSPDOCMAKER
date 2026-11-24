#!/bin/sh
# Daily database backup (PROJECT-REGISTER No. 199, Stage 0, task TK-001).
#
# Runs inside the "backup" service of docker-compose.prod.yml (postgres
# image, so pg_dump matches the database). Every 15 minutes it looks at the
# newest backup; when it is a day old (or there is none) it takes a new one:
#
#   /backups/<name>-backup-YYYY-MM-DD-HHMM.dump  (pg_dump custom format,
#                                                compressed; restore with
#                                                pg_restore — DEPLOY.md)
#
# A backup counts only after `pg_restore --list` can read it back. The
# newest BACKUP_KEEP (14) are kept, older ones removed. Every run is written
# to /backups/<name>-backup.log, and /backups/<name>-last-backup.txt says
# "ok <time> <file>"
# or "failed <time> <why>" — the app's alerts read that file and email the
# Super Admins when a backup failed or is more than a day late.
# A failed backup is tried again on the next 15-minute check.

set -u
DIR=/backups
# <name>: cspdocmaker for the live app, cspdocmaker-test for the test copy,
# so the two never mix or remove each other's backups in a shared folder.
NAME="${BACKUP_NAME:-cspdocmaker}"
KEEP="${BACKUP_KEEP:-14}"
EVERY_MINUTES="${BACKUP_EVERY_MINUTES:-1440}"
mkdir -p "$DIR"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*" | tee -a "$DIR/$NAME-backup.log"; }

status() { printf '%s %s %s\n' "$1" "$(date -u +%s)" "$2" > "$DIR/$NAME-last-backup.txt"; }

take() {
  name="$NAME-backup-$(date -u +%Y-%m-%d-%H%M).dump"
  part="$DIR/.$name.part"
  if ! err=$(pg_dump --no-owner --format=custom --file="$part" 2>&1); then
    rm -f "$part"
    log "FAILED: pg_dump: $err"
    status failed "pg_dump: $(echo "$err" | tr '\n' ' ' | cut -c1-300)"
    return 1
  fi
  if ! pg_restore --list "$part" >/dev/null 2>&1; then
    rm -f "$part"
    log "FAILED: the backup could not be read back"
    status failed "the backup file could not be read back"
    return 1
  fi
  mv "$part" "$DIR/$name"
  log "OK $name ($(du -h "$DIR/$name" | cut -f1))"
  status ok "$name"
  # Keep the newest $KEEP; remove the rest.
  ls -1t "$DIR"/"$NAME"-backup-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" |
    while read -r old; do rm -f "$old" && log "removed old $(basename "$old")"; done
  return 0
}

due() {
  newest=$(ls -1t "$DIR"/"$NAME"-backup-*.dump 2>/dev/null | head -1)
  [ -z "$newest" ] && return 0
  [ -n "$(find "$newest" -mmin +"$((EVERY_MINUTES - 10))")" ]
}

log "started: a backup every $EVERY_MINUTES minutes, keeping the newest $KEEP, in $DIR"
while :; do
  if due; then take || true; fi
  sleep 900
done
