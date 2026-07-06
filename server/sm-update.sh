#!/bin/bash
#
# StepMania dashboard update — processes an uploaded bundle.
#
# Triggered by sm-update.path when /var/www/stepmania-incoming/sm-bundle.zip
# is created/modified by a WebDAV PUT.  Unzips Save+Cache, runs the build,
# rsync-deploys to /var/www/stepmania/, cleans up.
#
# Runs as www-data via sm-update.service.  Logs to systemd-journal.
#
set -euo pipefail

INCOMING=/var/www/stepmania-incoming/sm-bundle.zip
WORK=/var/www/stepmania-work
SHARE=/usr/local/share/sm-dashboard
LOCK=/run/sm-update.lock

# Per-machine settings (SM_LIVE_DIR) installed alongside the build script by
# install.sh — see site.env.example. Env wins over file.
[ -f "$SHARE/site.env" ] && { set -a; . "$SHARE/site.env"; set +a; }
DEST="${SM_LIVE_DIR:-/var/www/stepmania}"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }

# Lock: skip silently if another instance is already running.
exec 9>"$LOCK"
flock -n 9 || { log "another instance is running, exiting"; exit 0; }

log "=== update triggered ==="

# 1. Validate incoming bundle ------------------------------------------------
if [ ! -f "$INCOMING" ]; then
    log "ERROR: no bundle at $INCOMING"
    exit 1
fi
SIZE=$(stat -c%s "$INCOMING")
log "bundle size: $((SIZE/1024/1024)) MB"
if [ "$SIZE" -lt 100000 ]; then
    log "ERROR: bundle suspiciously small ($SIZE bytes)"
    exit 1
fi
if ! unzip -tq "$INCOMING" >/dev/null 2>&1; then
    log "ERROR: bundle is not a valid zip"
    exit 1
fi

# 2. Extract to a fresh work dir --------------------------------------------
rm -rf "$WORK"
mkdir -p "$WORK/extract"
log "extracting..."
unzip -q -o "$INCOMING" -d "$WORK/extract"
log "extracted: $(du -sh "$WORK/extract" | cut -f1)"

# Locate Save/ and (optionally) Cache/Songs, Cache/Banners regardless of how
# deeply the bundle nests them (top-level, inside StepMania 5.1/, etc.).
SAVE=$(find "$WORK/extract" -maxdepth 4 -type d -name Save | head -1)
CACHE_SONGS=$(find "$WORK/extract" -maxdepth 5 -type d -path '*/Cache/Songs' | head -1)
CACHE_BANNERS=$(find "$WORK/extract" -maxdepth 5 -type d -path '*/Cache/Banners' | head -1)
if [ -z "$SAVE" ]; then
    log "ERROR: no Save/ directory in bundle"
    exit 1
fi
log "Save:          $SAVE"
log "Cache/Songs:   ${CACHE_SONGS:-(none)}"
log "Cache/Banners: ${CACHE_BANNERS:-(none)}"

# 3. Build -------------------------------------------------------------------
mkdir -p "$WORK/build"
log "building..."
if [ -n "$CACHE_BANNERS" ]; then export SM_BANNERS="$CACHE_BANNERS"; fi
# Persistent banner cache: $WORK is wiped per run and $SHARE isn't writable by
# www-data, so conversions are cached in a dedicated dir (set up by install.sh).
export SM_BANNER_CACHE=/var/www/stepmania-banner-cache
python3 "$SHARE/build_dashboard.py" "$SAVE" "$WORK/build" "${CACHE_SONGS:-}"

# 4. Atomic-ish deploy ------------------------------------------------------
# rsync renames each file atomically; the brief moment a request might
# see a half-updated banners/ dir is acceptable (page itself is text and
# is updated atomically per-file).
log "deploying to $DEST"
rsync -a --delete \
    --exclude='.gitignore' \
    "$WORK/build/" "$DEST/"
log "deployed: $(ls "$DEST" | tr '\n' ' ')"
log "data.json: $(stat -c%s "$DEST/data.json") bytes, $(date -r "$DEST/data.json" -Iseconds)"

# 5. Cleanup ----------------------------------------------------------------
rm -rf "$WORK"
rm -f "$INCOMING"
log "=== update complete ==="
