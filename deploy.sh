#!/usr/bin/env bash
#
# Deploy the StepMania dashboard to nginx.
#
# Two modes (auto-detected):
#   1. If $DEST is writable by the current user → no sudo needed.
#      Run with:   bash deploy.sh
#      (After the one-time setup:
#         sudo chown -R $USER:www-data /var/www/stepmania &&
#         sudo chmod -R g+w /var/www/stepmania &&
#         sudo chmod g+s /var/www/stepmania
#       …the build script will also auto-deploy on every build.)
#
#   2. Otherwise → needs sudo for the first-time install (file ownership and
#      the nginx location block). Run with:  sudo bash deploy.sh
#
# Paths:
#   SRC   defaults to ./public next to this script (auto-located, no need to
#         edit when the checkout moves).
#   DEST  is taken from the "liveDir" key in ./config.json (the same value
#         build_dashboard.py uses for auto-deploy). There is no built-in
#         fallback — if liveDir is missing and $DEST isn't set, this script
#         refuses to run.
# Override either with env vars, e.g.:
#     SRC=/path/to/public DEST=/var/www/sm bash deploy.sh
#
set -euo pipefail

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_JSON="${SCRIPT_DIR}/config.json"
CONFIG_DEST=$(python3 - "$CONFIG_JSON" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        print(json.load(fh).get("liveDir", "") or "")
except Exception:
    pass
PY
)

SRC="${SRC:-${SCRIPT_DIR}/public}"
DEST="${DEST:-${CONFIG_DEST}}"
if [ -z "$DEST" ]; then
    red "No deploy target. Set \"liveDir\" in $CONFIG_JSON, or pass DEST=… on the command line."
    inf "Example:   DEST=/var/www/stepmania bash $0"
    exit 1
fi
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"
URL_PATH="/stepmania/"
PUBLIC_URL="https://example.com${URL_PATH}"

# Pick mode based on whether we can write $DEST without escalation.
ROOT=0; [ "$(id -u)" -eq 0 ] && ROOT=1
USER_DEPLOY=0
if [ "$ROOT" -eq 0 ] && [ -d "$DEST" ] && [ -w "$DEST" ]; then
    USER_DEPLOY=1
fi
if [ "$ROOT" -eq 0 ] && [ "$USER_DEPLOY" -eq 0 ]; then
    red "Can't write $DEST as $(whoami)."
    inf "Either run with sudo:  sudo bash $0"
    inf "Or do this one-time fix so you never need sudo again:"
    inf "  sudo chown -R \$USER:www-data $DEST && sudo chmod -R g+w $DEST && sudo chmod g+s $DEST"
    exit 1
fi

# --- 1. check source files -------------------------------------------------
for f in index.html data.json; do
  [ -f "$SRC/$f" ] || { red "Missing $SRC/$f — run build_dashboard.py first."; exit 1; }
done

# --- 2. copy files (full mirror so banners/, nobanner.svg etc. come along) ---
inf "Copying dashboard -> $DEST  (mode: $([ "$ROOT" -eq 1 ] && echo sudo || echo user))"
mkdir -p "$DEST"
# Clear stale banners first, then rsync-style mirror of $SRC into $DEST.
rm -rf "$DEST/banners"
cp -r "$SRC"/. "$DEST/"
if [ "$ROOT" -eq 1 ]; then
    chown -R www-data:www-data "$DEST" 2>/dev/null || true
fi
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod 644 {} +
grn "  in place: $(ls -1 "$DEST" | tr '\n' ' ')"

# Steps 3 (nginx) only runs as root; in user-deploy mode we assume it's
# already configured (otherwise the URL would be 404'ing, which the user
# would have noticed).
if [ "$USER_DEPLOY" -eq 1 ]; then
    grn "Done.  Visit:  ${PUBLIC_URL}   (Ctrl+F5 to defeat data.json cache)"
    exit 0
fi

# --- 3. nginx location block ----------------------------------------------
if [ ! -f "$NGINX_SITE" ]; then
  red "nginx site not found: $NGINX_SITE"
  inf "Files are deployed; add a 'location ^~ /stepmania/' block manually (see README.md)."
  exit 1
fi

if grep -q "location[[:space:]]*\^~[[:space:]]*${URL_PATH}" "$NGINX_SITE"; then
  grn "nginx: location ${URL_PATH} already present — skipping edit."
else
  BAK="${NGINX_SITE}.bak.$(date +%Y%m%d%H%M%S)"
  cp "$NGINX_SITE" "$BAK"
  inf "nginx: backup saved -> $BAK"

  # Insert the block right after the 'index index.html;' line, which appears
  # only inside the 'listen 443' server block of this site.
  awk -v dest="$DEST" '
    { print }
    !ins && /index[ \t]+index\.html;/ {
      print "";
      print "    location ^~ /stepmania/ {";
      print "        alias " dest "/;";
      print "        index index.html;";
      print "    }";
      ins=1
    }
    END { if (!ins) exit 3 }
  ' "$BAK" > "$NGINX_SITE" || {
      red "nginx: could not find an insertion point ('index index.html;'). Restoring.";
      cp "$BAK" "$NGINX_SITE";
      inf "Add the location block manually (see README.md).";
      exit 1; }

  if nginx -t; then
    systemctl reload nginx
    grn "nginx: config valid, reloaded."
  else
    red "nginx: config test FAILED — restoring backup."
    cp "$BAK" "$NGINX_SITE"
    nginx -t || true
    exit 1
  fi
fi

grn "Done.  Visit:  ${PUBLIC_URL}   (enter your class login)"
