#!/bin/sh
# Build deploy/.env.production on the server (see DEPLOY.md).
#
#   sh deploy/make-env.sh <address> <laptop-env-file>
#
# <address> is where people open the app, without https://:
#   docs.example.com              its own domain (Caddy takes 80/443)
#   indev.eko.in/csp-docmaker     a path on a domain another web server
#                                 already serves (Caddy listens privately
#                                 on 127.0.0.1:8088; see DEPLOY.md)
#
# Takes the values marked COPY in deploy/.env.production.example from the
# laptop's backend/.env (copied to the server), makes fresh random secrets
# for the values marked NEW, sets the domain, and then deletes the copied
# laptop file. Prints only the names of settings, never their values.
set -e
cd "$(dirname "$0")/.."

ADDRESS="$1"
LAPTOP_ENV="$2"
OUT=deploy/.env.production
if [ -z "$ADDRESS" ] || [ ! -f "$LAPTOP_ENV" ]; then
    echo "usage: sh deploy/make-env.sh <address> <laptop-env-file>" >&2
    exit 1
fi
case "$ADDRESS" in
    http*|*//*|*" "*) echo "give the address without https://, e.g. indev.eko.in/csp-docmaker" >&2; exit 1 ;;
esac
ADDRESS="${ADDRESS%/}"
DOMAIN="${ADDRESS%%/*}"
BASE_PATH=""
[ "$DOMAIN" != "$ADDRESS" ] && BASE_PATH="/${ADDRESS#*/}"
if [ -f "$OUT" ]; then
    echo "$OUT already exists — remove it first if you mean to rebuild it" >&2
    exit 1
fi

umask 077
tr -d '\r' < deploy/.env.production.example > "$OUT"

# Replace KEY=... in $OUT with KEY=<value>, whatever characters the value has.
set_value() {
    tmp="$OUT.tmp"
    # Passed through the environment, not awk -v: -v would turn a "\r" or
    # "\n" inside a password into a control character.
    SET_KEY="$1" SET_VALUE="$2" awk 'BEGIN { FS = "="; k = ENVIRON["SET_KEY"]; v = ENVIRON["SET_VALUE"] }
        $1 == k { print k "=" v; done = 1; next } { print }
        END { if (!done) print k "=" v }' "$OUT" > "$tmp" && mv "$tmp" "$OUT"
}

# Read KEY's value from the laptop file (first match, surrounding quotes kept
# as written; Docker Compose removes them).
laptop_value() {
    grep -m1 "^$1=" "$LAPTOP_ENV" | cut -d= -f2- | tr -d '\r'
}

COPY_KEYS="SUPER_ADMIN_EMAILS ALLOWED_EMAIL_DOMAIN
GOOGLE_SHEETS_ID GOOGLE_SHEETS_RM_SHEET_NAME GOOGLE_SHEETS_ADMIN_SHEET_NAME
GOOGLE_SHEETS_CSP_SHEET_ID GOOGLE_SHEETS_CSP_SHEET_NAME GOOGLE_SHEETS_SUBKO_SHEET_NAME
GOOGLE_SHEETS_SYNC_INTERVAL_MINUTES CSP_SYNC_INTERVAL_MINUTES
EMAIL_METHOD SMTP_HOST SMTP_PORT SMTP_USE_TLS SMTP_USERNAME SMTP_PASSWORD
SMTP_FROM_EMAIL SMTP_FROM_NAME
ZOHO_DATA_CENTRE ZOHO_CLIENT_ID ZOHO_CLIENT_SECRET ZOHO_REFRESH_TOKEN
PHOTO_PLACEHOLDER_ALLOWED"

copied=0
for key in $COPY_KEYS; do
    value="$(laptop_value "$key")"
    # Docker Compose reads "$" as "insert a variable"; "$$" keeps it literal.
    value="$(printf '%s' "$value" | sed 's/\$/$$/g')"
    if [ -n "$value" ]; then
        set_value "$key" "$value"
        copied=$((copied + 1))
    fi
done

set_value DOMAIN "$DOMAIN"
set_value PUBLIC_APP_URL "https://$ADDRESS"
set_value BASE_PATH "$BASE_PATH"
if [ -n "$BASE_PATH" ]; then
    # Another web server owns the domain: stay off its ports.
    set_value CADDYFILE "Caddyfile.behind-proxy"
    set_value HTTP_BIND "127.0.0.1:8088"
    # Unused behind a proxy (no HTTPS here) but must be a free port; 8443
    # is often taken already (it was on indev.eko.in).
    set_value HTTPS_BIND "127.0.0.1:18443"
fi
set_value APP_SECRET_KEY "$(openssl rand -hex 32)"
set_value JWT_SECRET_KEY "$(openssl rand -hex 32)"
set_value DATABASE_PASSWORD "$(openssl rand -hex 24)"
chmod 600 "$OUT"

# The laptop file held every secret; it is not needed any more.
if command -v shred >/dev/null 2>&1; then shred -u "$LAPTOP_ENV"; else rm -f "$LAPTOP_ENV"; fi

echo "Created $OUT for https://$ADDRESS ($copied values copied, 3 new secrets made)."
if [ -n "$BASE_PATH" ]; then
    echo "Served under $BASE_PATH: the app will listen on 127.0.0.1:8088 for the web server of $DOMAIN (see DEPLOY.md)."
fi
empty="$(grep -E '^[A-Z_]+=$' "$OUT" | cut -d= -f1 | tr '\n' ' ')"
if [ -n "$empty" ]; then
    echo "Still empty (fill in with: nano $OUT): $empty"
else
    echo "Every setting has a value."
fi
