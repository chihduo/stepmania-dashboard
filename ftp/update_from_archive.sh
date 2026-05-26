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
#   4. Runs ../build_dashboard.py against those paths
#   5. Cleans up the extracted dir on success
#
# This does NOT deploy to /var/www/stepmania/. Run ../deploy.sh after, when
# you're happy with the result.
#
set -euo pipefail

FTP_DIR="$(cd "$(dirname "$0")" && pwd)"
DASH_DIR="$(cd "$FTP_DIR/.." && pwd)"
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
grn "  Cache/Songs:   ${CACHE_SONGS:-(none — artist/title will be blank)}"
grn "  Cache/Banners: ${CACHE_BANNERS:-(none — banners will use placeholder)}"

# 5. Build ------------------------------------------------------------------
inf "Building dashboard..."
if [ -n "$CACHE_BANNERS" ]; then
    export SM_BANNERS="$CACHE_BANNERS"
fi
python3 "$DASH_DIR/build_dashboard.py" \
    "$SAVE" \
    "$DASH_DIR/public" \
    "${CACHE_SONGS:-}"

# 6. Cleanup ----------------------------------------------------------------
inf "Cleaning up $EXTRACT/"
rm -rf "$EXTRACT"

cat <<EOF

$(grn "Done.")  Dashboard data written to:  $DASH_DIR/public/

If /var/www/stepmania is user-writable, build_dashboard.py already auto-
deployed (look for 'Auto-deployed to ...' above). Otherwise push manually:
    bash      $DASH_DIR/deploy.sh    # after the one-time chown
    sudo bash $DASH_DIR/deploy.sh    # otherwise

Browser cache: Ctrl+F5 to defeat data.json caching.
EOF
