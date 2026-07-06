#!/bin/bash
#
# Daily update: zip the Windows StepMania Save+Cache and PUT to the dashboard
# server. Designed to run from WSL2 Ubuntu via cron.
#
#   ~/.local/bin/wsl-update.sh
#
# Reads Windows StepMania data through /mnt/c (no Python/PIL needed on this side
# — the server does the build). Credentials come from ~/.netrc (chmod 600).
#
# Per-machine settings (SM_HOST, SM_APPDATA) are read from site.env — installed
# to ~/.config/sm-dashboard/site.env by wsl-install.sh, or found next to the
# repo checkout. Any can also be overridden by an env var of the same name:
#   SM_APPDATA="/mnt/c/Users/Foo/AppData/Roaming/StepMania 5.1" wsl-update.sh
#
set -euo pipefail

# Per-machine settings: installed location first, then a repo checkout next to
# this script. Env vars already set before running still win over the file.
REPO=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || true)
SITE_ENV="${SM_SITE_ENV:-}"
if [ -z "$SITE_ENV" ]; then
    for cand in "$HOME/.config/sm-dashboard/site.env" "${REPO:-}/site.env"; do
        [ -n "$cand" ] && [ -f "$cand" ] && { SITE_ENV="$cand"; break; }
    done
fi
[ -n "$SITE_ENV" ] && [ -f "$SITE_ENV" ] && { set -a; . "$SITE_ENV"; set +a; }

LOG_DIR="$HOME/.local/share/sm-update"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/wsl-update.log"
exec >>"$LOG" 2>&1

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
log "=== wsl-update start ==="

# 1. Locate Windows StepMania 5.1 ------------------------------------------
APPDATA="${APPDATA:-${SM_APPDATA:-}}"
if [ -z "$APPDATA" ]; then
    APPDATA=$(ls -d /mnt/c/Users/*/AppData/Roaming/"StepMania 5.1" 2>/dev/null | head -1 || true)
fi
if [ -z "$APPDATA" ] || [ ! -d "$APPDATA" ]; then
    log "ERROR: StepMania 5.1 not found. Set APPDATA env var."
    exit 1
fi
log "APPDATA: $APPDATA"
[ -d "$APPDATA/Save" ]  || { log "ERROR: $APPDATA/Save missing"; exit 1; }
[ -d "$APPDATA/Cache" ] || { log "ERROR: $APPDATA/Cache missing"; exit 1; }

# 2. Bundle ----------------------------------------------------------------
HOST="${SM_HOST:-your-host}"
URL="${URL:-https://${HOST}/stepmania-upload/sm-bundle.zip}"
VERIFY_URL="${VERIFY_URL:-https://${HOST}/stepmania/data.json}"

WORK=$(mktemp -d -t sm-update-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
BUNDLE="$WORK/sm-bundle.zip"

SAVE_SIZE=$(du -sh "$APPDATA/Save" | cut -f1)
CACHE_SIZE=$(du -sh "$APPDATA/Cache" | cut -f1)
log "bundling Save ($SAVE_SIZE) + Cache ($CACHE_SIZE)"
( cd "$APPDATA" && zip -qr "$BUNDLE" Save Cache )
SIZE_MB=$(( $(stat -c%s "$BUNDLE") / 1024 / 1024 ))
log "bundle: ${SIZE_MB} MB"

# 3. Upload ----------------------------------------------------------------
log "uploading -> $URL"
if ! curl -fsS --netrc \
        --max-time 1800 \
        --retry 2 --retry-delay 30 --retry-all-errors \
        -T "$BUNDLE" "$URL"; then
    log "ERROR: upload failed (curl exit $?)"
    exit 1
fi
log "upload OK"

# 4. Verify the server processed it (server side fires within ~ms of upload)
sleep 30
HDR=$(curl -fsS --netrc -I "$VERIFY_URL" 2>&1 | tr -d '\r' || true)
LM=$(echo "$HDR" | awk -F': ' 'BEGIN{IGNORECASE=1}/^last-modified/{print $2}')
CL=$(echo "$HDR" | awk -F': ' 'BEGIN{IGNORECASE=1}/^content-length/{print $2}')
log "data.json: last-modified=${LM:-?}, content-length=${CL:-?}"
log "=== wsl-update end ==="
