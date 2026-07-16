#!/usr/bin/env bash
#
# Rebuild the dashboard from a StepMania archive uploaded into this folder.
#
# Drop one of these files here:
#     StepMania 5.rar
#     StepMania 5.zip
# then run:
#     bash update_from_archive.sh
#
# The script:
#   1. Locates the archive
#   2. Extracts it to ./extracted/  (this folder, transient)
#   3. Finds Save/ and Cache/{Songs,Banners} inside (handles nested layouts)
#   4. Syncs them into the repo's canonical data dirs (../../savedata/Save and
#      ../../cachedata/Cache/) — the single source of truth every build reads,
#      whether triggered here or by running ../build_dashboard.py directly
#   5. Runs ../build_dashboard.py (no args — it reads the canonical dirs)
#   6. Cleans up the extracted dir on success
#
set -euo pipefail

FTP_DIR="$(cd "$(dirname "$0")" && pwd)"
DASH_DIR="$(cd "$FTP_DIR/.." && pwd)"
REPO_DIR="$(cd "$DASH_DIR/.." && pwd)"
SAVEDATA="$REPO_DIR/savedata"
CACHEDATA="$REPO_DIR/cachedata"
EXTRACT="$FTP_DIR/extracted"

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

# 1. Find the archive --------------------------------------------------------
ARCHIVE=""
for cand in "StepMania 5.rar" "StepMania 5.zip"; do
    if [ -f "$FTP_DIR/$cand" ]; then
        ARCHIVE="$FTP_DIR/$cand"; break
    fi
done
if [ -z "$ARCHIVE" ]; then
    red "No archive found."
    inf "Drop 'StepMania 5.rar' or 'StepMania 5.zip' into:"
    inf "  $FTP_DIR"
    exit 1
fi
inf "Found: $ARCHIVE  ($(du -h "$ARCHIVE" | cut -f1))"

# 2. Validate the right tool is installed -----------------------------------
# For .rar accept either `unrar` (dedicated extractor) or `rar` (the full
# RARLAB tool) — both support the same 'x -idq -o+' extract syntax.
RAR_BIN=""
case "$ARCHIVE" in
    *.rar)
        for cmd in unrar rar; do
            command -v "$cmd" >/dev/null 2>&1 && { RAR_BIN="$cmd"; break; }
        done
        if [ -z "$RAR_BIN" ]; then
            red "Neither 'unrar' nor 'rar' is installed. Install one with:"
            inf "  sudo apt-get install unrar"
            inf "(or re-export the archive as .zip instead — unzip is already installed)"
            exit 1
        fi ;;
    *.zip)
        command -v unzip >/dev/null 2>&1 || { red "unzip not installed?"; exit 1; } ;;
esac

# 3. Extract ----------------------------------------------------------------
rm -rf "$EXTRACT"
mkdir -p "$EXTRACT"
inf "Extracting..."
case "$ARCHIVE" in
    *.rar) "$RAR_BIN" x -idq -o+ "$ARCHIVE" "$EXTRACT/" ;;
    *.zip) unzip -q -o "$ARCHIVE" -d "$EXTRACT" ;;
esac
grn "  extracted: $(du -sh "$EXTRACT" | cut -f1)"

# 4. Locate Save/ and Cache/{Songs,Banners} regardless of nesting -----------
SAVE=$(find "$EXTRACT" -maxdepth 5 -type d -name Save | head -1)
CACHE_SONGS=$(find "$EXTRACT" -maxdepth 6 -type d -path '*/Cache/Songs' | head -1)
CACHE_BANNERS=$(find "$EXTRACT" -maxdepth 6 -type d -path '*/Cache/Banners' | head -1)

if [ -z "$SAVE" ]; then
    red "No Save/ directory found in archive."
    inf "Looked under $EXTRACT (maxdepth 5). Contents:"
    ls -la "$EXTRACT" | head -20
    exit 1
fi
grn "  Save:          $SAVE"
# Cache/ supplies song titles/artists and ~90% of banners, and it CANNOT be
# reconstructed from Save/ alone. If the bundle omitted it, warn loudly: the
# sync step below keeps the previous (now-stale) Cache rather than failing, so
# without this the problem is silent — the dashboard just shows old metadata.
if [ -z "$CACHE_SONGS" ] && [ -z "$CACHE_BANNERS" ]; then
    red "  Cache/Songs:   (MISSING)"
    red "  Cache/Banners: (MISSING)"
    echo
    red "WARNING: this bundle contains no ./Cache folder."
    red "  Titles, artists, and most banners come from Cache/. This build will"
    red "  reuse the PREVIOUS Cache if one exists (dashboard may be stale), or"
    red "  else fall back to folder names and placeholder banners."
    red "  Fix: re-export the bundle including BOTH the 'Save' and 'Cache' folders."
    echo
else
    [ -n "$CACHE_SONGS" ]   && grn "  Cache/Songs:   $CACHE_SONGS" \
                            || red "  Cache/Songs:   (MISSING — titles/artists will be stale or blank)"
    [ -n "$CACHE_BANNERS" ] && grn "  Cache/Banners: $CACHE_BANNERS" \
                            || red "  Cache/Banners: (MISSING — banners will be stale or placeholder)"
fi

# 5. Sync into the canonical data dirs ---------------------------------------
# All builds — this script or a direct `python3 build_dashboard.py` — read
# from savedata/ + cachedata/, so the archive becomes the new single source.
inf "Syncing Save -> $SAVEDATA/Save/"
mkdir -p "$SAVEDATA"
rsync -a --delete "$SAVE/" "$SAVEDATA/Save/"
if [ -n "$CACHE_SONGS" ]; then
    inf "Syncing Cache/Songs -> $CACHEDATA/Cache/Songs/"
    mkdir -p "$CACHEDATA/Cache"
    rsync -a --delete "$CACHE_SONGS/" "$CACHEDATA/Cache/Songs/"
else
    inf "Archive has no Cache/Songs — keeping the existing $CACHEDATA/Cache/Songs/"
fi
if [ -n "$CACHE_BANNERS" ]; then
    inf "Syncing Cache/Banners -> $CACHEDATA/Cache/Banners/"
    mkdir -p "$CACHEDATA/Cache"
    rsync -a --delete "$CACHE_BANNERS/" "$CACHEDATA/Cache/Banners/"
else
    inf "Archive has no Cache/Banners — keeping the existing $CACHEDATA/Cache/Banners/"
fi

# 6. Build (defaults resolve to the canonical dirs synced above) -------------
inf "Building dashboard..."
python3 "$DASH_DIR/build_dashboard.py"

# 7. Cleanup ----------------------------------------------------------------
inf "Cleaning up $EXTRACT/"
rm -rf "$EXTRACT"
# Mark the archive as applied so a re-run can't silently regress the canonical
# data dirs to this (by-then stale) snapshot. Drop a new archive to update again.
APPLIED="$ARCHIVE.applied-$(date +%Y%m%d%H%M%S)"
mv "$ARCHIVE" "$APPLIED"
inf "Archive marked applied: $(basename "$APPLIED")"

cat <<EOF

$(grn "Done.")  Canonical data updated ($SAVEDATA, $CACHEDATA);
dashboard written to $DASH_DIR/public/

If /var/www/stepmania is user-writable, build_dashboard.py already auto-
deployed (look for 'Auto-deployed to ...' above). Otherwise push manually:
    bash      $DASH_DIR/deploy.sh    # after the one-time chown
    sudo bash $DASH_DIR/deploy.sh    # otherwise

Browser cache: Ctrl+F5 to defeat data.json caching.
EOF
