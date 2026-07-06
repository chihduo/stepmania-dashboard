#!/usr/bin/env bash
#
# Server-side install for the daily WSL→dashboard upload pipeline.
#   sudo bash server/install.sh
#
# What it does (all idempotent):
#   1. Installs build_dashboard.py + page assets to /usr/local/share/sm-dashboard/
#      (so www-data can read them without needing access to your home dir).
#   2. Installs sm-update.sh to /usr/local/bin/.
#   3. Installs sm-update.{path,service} systemd units, enables the .path watcher.
#   4. Creates working dirs owned by www-data:
#        /var/www/stepmania-incoming/  (nginx writes uploads here)
#        /var/www/stepmania-incoming/.tmp/  (nginx body temp on same FS)
#        /var/www/stepmania-work/  (build scratch)
#   5. Edits /etc/nginx/sites-enabled/default to add the upload location
#      and increased body-size/timeouts (timestamped backup, nginx -t, rollback
#      on failure). Skipped if already present.
#
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Please run with sudo:  sudo bash $0"; exit 1; }

REPO=$(cd "$(dirname "$0")/.." && pwd)
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"

# Per-machine settings (SM_HOST, …) — see site.env.example. Env wins over file.
SITE_ENV="${SITE_ENV:-$REPO/site.env}"
[ -f "$SITE_ENV" ] && { set -a; . "$SITE_ENV"; set +a; }

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

# 1. Build script + page assets (system-readable) ---------------------------
inf "Installing build script + assets to /usr/local/share/sm-dashboard/"
install -d -m 755 /usr/local/share/sm-dashboard
install -m 644 "$REPO/build_dashboard.py" /usr/local/share/sm-dashboard/
install -m 644 "$REPO/index.html"         /usr/local/share/sm-dashboard/
install -m 644 "$REPO/nobanner.svg"       /usr/local/share/sm-dashboard/
install -m 644 "$REPO/config.json"        /usr/local/share/sm-dashboard/
# Per-machine settings (player name, live dir) that the build reads — see
# site.env.example. Skipped if you haven't created site.env yet.
[ -f "$SITE_ENV" ] && install -m 644 "$SITE_ENV" /usr/local/share/sm-dashboard/site.env

# 2. Processing script ------------------------------------------------------
inf "Installing /usr/local/bin/sm-update.sh"
install -m 755 "$REPO/server/sm-update.sh" /usr/local/bin/sm-update.sh

# 3. systemd units ----------------------------------------------------------
inf "Installing systemd units"
install -m 644 "$REPO/server/sm-update.path"    /etc/systemd/system/sm-update.path
install -m 644 "$REPO/server/sm-update.service" /etc/systemd/system/sm-update.service
systemctl daemon-reload

# 4. Working directories ----------------------------------------------------
inf "Creating work dirs owned by www-data"
install -d -m 755 -o www-data -g www-data /var/www/stepmania-incoming
install -d -m 755 -o www-data -g www-data /var/www/stepmania-incoming/.tmp
install -d -m 755 -o www-data -g www-data /var/www/stepmania-work
# Persistent banner-conversion cache — survives across runs (stepmania-work is
# wiped per run), so each banner is decoded once ever. sm-update.sh points
# build_dashboard.py at it via $SM_BANNER_CACHE.
install -d -m 755 -o www-data -g www-data /var/www/stepmania-banner-cache

# 5. nginx upload location --------------------------------------------------
if [ ! -f "$NGINX_SITE" ]; then
    red "nginx site not found: $NGINX_SITE"
    inf "Add the snippet manually (see server/nginx-snippet.conf)."
else
    if grep -q 'location[[:space:]]*/stepmania-upload/' "$NGINX_SITE"; then
        grn "nginx: /stepmania-upload/ location already present — skipping edit."
    else
        BAK="${NGINX_SITE}.bak.$(date +%Y%m%d%H%M%S)"
        cp "$NGINX_SITE" "$BAK"
        inf "nginx: backup saved -> $BAK"

        # Insert the snippet right after the existing /stepmania/ location's
        # closing brace (deploy.sh added that block). If we can't find that,
        # bail and let the user paste manually.
        awk '
            { print }
            /location[ \t]+\^~[ \t]+\/stepmania\// { inblk=1 }
            inblk && /^[ \t]*}/ && !ins {
                print ""
                print "    # --- StepMania dashboard upload endpoint (sm-update pipeline) ---"
                print "    client_max_body_size 400m;"
                print "    client_body_timeout 600s;"
                print "    send_timeout 600s;"
                print ""
                print "    location /stepmania-upload/ {"
                print "        if ($request_uri != \"/stepmania-upload/sm-bundle.zip\") { return 405; }"
                print "        dav_methods PUT;"
                print "        create_full_put_path on;"
                print "        dav_access user:rw group:r all:r;"
                print "        alias /var/www/stepmania-incoming/;"
                print "        client_body_temp_path /var/www/stepmania-incoming/.tmp;"
                print "        limit_except PUT { deny all; }"
                print "    }"
                inblk=0; ins=1
            }
            END { if (!ins) exit 3 }
        ' "$BAK" > "$NGINX_SITE" || {
            red "nginx: could not find the existing /stepmania/ location to insert after. Restoring."
            cp "$BAK" "$NGINX_SITE"
            inf "Run deploy.sh first (to add the /stepmania/ block), then re-run this."
            exit 1
        }

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
fi

# 6. Enable the path watcher ------------------------------------------------
systemctl enable --now sm-update.path
grn "sm-update.path enabled: $(systemctl is-active sm-update.path)"

cat <<EOF

============================================================================
Server is ready. Test the pipeline by uploading the current public/ as if it
were a bundle (sanity check):

  sudo -u www-data touch /var/www/stepmania-incoming/sm-bundle.zip   # no-op
  journalctl -fu sm-update.service                                   # watch

Real upload from a client (with basic auth in ~/.netrc):

  curl -fsS --netrc -T sm-bundle.zip \\
       https://${SM_HOST:-<your-host>}/stepmania-upload/sm-bundle.zip

============================================================================
EOF
