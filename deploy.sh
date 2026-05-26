#!/usr/bin/env bash
#
# Deploy the StepMania dashboard to nginx.  Run with sudo:
#     sudo bash deploy.sh
#
# What it does (all idempotent + reversible):
#   1. Copies index.html + data.json to /var/www/stepmania/
#   2. Adds a 'location ^~ /stepmania/' block to the nginx site (with backup),
#      tests the config, and reloads nginx. Rolls back if the test fails.
#
# Override defaults with env vars, e.g.:
#     sudo SRC=/path/to/public DEST=/var/www/sm bash deploy.sh
#
set -euo pipefail

SRC="${SRC:-/home/claude/stepmania/dashboard/public}"
DEST="${DEST:-/var/www/stepmania}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"
URL_PATH="/stepmania/"
PUBLIC_URL="https://example.com${URL_PATH}"

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { red "Please run with sudo:  sudo bash $0"; exit 1; }

# --- 1. check source files -------------------------------------------------
for f in index.html data.json; do
  [ -f "$SRC/$f" ] || { red "Missing $SRC/$f — run build_dashboard.py first."; exit 1; }
done

# --- 2. copy files (full mirror so banners/, nobanner.svg etc. come along) ---
inf "Copying dashboard -> $DEST"
mkdir -p "$DEST"
# Clear stale banners first, then rsync-style mirror of $SRC into $DEST.
rm -rf "$DEST/banners"
cp -r "$SRC"/. "$DEST/"
chown -R www-data:www-data "$DEST" 2>/dev/null || true
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod 644 {} +
grn "  in place: $(ls -1 "$DEST" | tr '\n' ' ')"

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
