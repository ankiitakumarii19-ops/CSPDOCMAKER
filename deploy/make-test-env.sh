#!/usr/bin/env bash
# Makes deploy/.env.test for the TEST COPY of the app (No. 173) from the
# real deploy/.env.production — same sign-in list, same sender for the
# sign-in code — and changes what must never be shared:
#
#   * TEST_COPY=true      no WhatsApp ever goes; every email but the
#                         sign-in code is held; every screen says TEST COPY
#   * its own database password, secrets, sign-in cookie, images and
#     documents folder (../CSP_Documents_test)
#   * served at <live address>-test, e.g. https://indev.eko.in/csp-docmaker-test,
#     on 127.0.0.1:8089
#   * the CSP / Calling / Lead / Address sheets and Zoho are blanked, so the
#     test copy never reads or writes the real ones. To test with data, make
#     a COPY of CSPDATA in Google Sheets, share it with the service account,
#     and run:  TEST_CSP_SHEET_ID=<the copy's id> deploy/make-test-env.sh
#
# Run on the server, in the app folder:  bash deploy/make-test-env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

src=deploy/.env.production
dst=deploy/.env.test
[ -f "$src" ] || { echo "$src not found — run this in the app folder on the server."; exit 1; }
[ -e "$dst" ] && { echo "$dst already exists. Remove it first for a fresh one."; exit 1; }

cp "$src" "$dst"
chmod 600 "$dst"

set_value() {
  local key=$1 value=$2
  if grep -q "^${key}=" "$dst"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$dst"
  else
    printf '%s=%s\n' "$key" "$value" >> "$dst"
  fi
}
secret() { openssl rand -hex 32; }

live_url=$(grep '^PUBLIC_APP_URL=' "$src" | cut -d= -f2- || true)
live_base=$(grep '^BASE_PATH=' "$src" | cut -d= -f2- || true)
[ -n "$live_base" ] || { echo "BASE_PATH is blank in $src: the test copy needs the live app to run under a path (e.g. /csp-docmaker)."; rm -f "$dst"; exit 1; }

printf '\n# ---- TEST COPY (No. 173) — made by deploy/make-test-env.sh ----\n' >> "$dst"
set_value TEST_COPY true
set_value EMAILS_PAUSED true
set_value ENV_FILE deploy/.env.test
set_value IMAGE_PREFIX cspdocmaker-test
set_value DOCUMENTS_ARCHIVE_HOST ../CSP_Documents_test
set_value BASE_PATH "${live_base%/}-test"
set_value PUBLIC_APP_URL "${live_url%/}-test"
set_value CADDYFILE Caddyfile.behind-proxy
set_value HTTP_BIND 127.0.0.1:8089
set_value HTTPS_BIND 127.0.0.1:8449
set_value SESSION_COOKIE_NAME cspdm_test_session
set_value DATABASE_PASSWORD "$(secret)"
set_value JWT_SECRET_KEY "$(secret)"
set_value APP_SECRET_KEY "$(secret)"
for key in CALLING_SHEET_ID LEAD_SHEET_ID ADDRESS_SHEET_ID \
           ZOHO_CLIENT_ID ZOHO_CLIENT_SECRET ZOHO_REFRESH_TOKEN; do
  set_value "$key" ""
done
set_value GOOGLE_SHEETS_CSP_SHEET_ID "${TEST_CSP_SHEET_ID:-}"
set_value VERIFY_OLD_CSPS_ENABLED false

mkdir -p ../CSP_Documents_test
echo "Made $dst (TEST_COPY=true, served at ${live_url%/}-test)."
echo "Start it with:"
echo "  docker compose -p cspdocmaker-test -f docker-compose.prod.yml --env-file $dst up -d --build"
