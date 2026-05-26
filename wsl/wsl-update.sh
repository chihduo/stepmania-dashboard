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
# Override defaults with env vars, e.g.:
#   APPDATA=/mnt/c/Users/Foo/AppData/Roaming/StepMania5 wsl-update.sh
#
set -euo pipefail

LOG_DIR="$HOME/.local/share/sm-update"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/wsl-update.log"
exec >>"$LOG" 2>&1

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
log "=== wsl-update start ==="

# 1. Locate Windows StepMania 5.1 ------------------------------------------
if [ -z "${APPDATA:-}" ]; then
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
URL="${URL:-https://example.com/stepmania-upload/sm-bundle.zip}"
VERIFY_URL="${VERIFY_URL:-https://example.com/stepmania/data.json}"

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
