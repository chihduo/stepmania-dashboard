#!/bin/bash
#
# One-shot: generate banner PNGs for songs whose banner is a *video*
# (#BANNER:foo.avi;) by extracting one frame with ffmpeg, directly in WSL.
#
# StepMania pre-renders *image* banners into Cache/Banners, but never video
# banners — so the dashboard build can't see them. This script scans every
# song's .sm/.ssc for a video #BANNER tag, grabs a frame from the video, and
# writes a small PNG named the way the dashboard's lookup expects:
#   "Songs_<pack>_<song>_<banner-file>.png"
# (the video filename is kept in the name, with .png appended).
#
# Only the PNGs (a few KB each) need to be copied to the server — not the
# videos themselves. Raw videos staged on the server still work as a fallback;
# pre-extracted PNGs are preferred.
#
# Usage (from WSL; needs ffmpeg: sudo apt-get install ffmpeg):
#   bash collect-video-banners.sh SONGS_DIR [OUT_DIR]
#     SONGS_DIR  your local Songs folder (required), e.g.
#                '/mnt/c/Users/You/AppData/Roaming/StepMania 5.1/Songs'
#     OUT_DIR    default: ./video-banners
#
# Then copy OUT_DIR to the server, into the repo's dashboard/video-banners/
# (or wherever $SM_VIDEO_BANNERS points), e.g.:
#   scp video-banners/* server:~/stepmania_dashboard/dashboard/video-banners/
# and rebuild:  python3 build_dashboard.py
#
set -euo pipefail

SONGS_DIR="${1:-}"
OUT_DIR="${2:-./video-banners}"
MAX_W=160

command -v ffmpeg >/dev/null 2>&1 || {
    echo "ERROR: ffmpeg not found — install it first:  sudo apt-get install ffmpeg" >&2
    exit 1
}

if [ -z "$SONGS_DIR" ] || [ ! -d "$SONGS_DIR" ]; then
    echo "ERROR: Songs dir not found — pass it as the first argument." >&2
    echo "  bash $0 '/mnt/c/path/to/StepMania 5.1/Songs'" >&2
    exit 1
fi
echo "Songs dir: $SONGS_DIR"
mkdir -p "$OUT_DIR"

# Frame 0 of looping banner videos is often black — seek to 1s first, fall
# back to the very first frame for clips shorter than that.
extract_frame() {  # $1=src video  $2=dest png
    local seek
    for seek in 1 0; do
        if ffmpeg -y -loglevel error -ss "$seek" -i "$1" -frames:v 1 \
                  -vf "scale='min($MAX_W,iw)':-1" "$2" </dev/null \
           && [ -s "$2" ]; then
            return 0
        fi
    done
    rm -f "$2"
    return 1
}

extracted=0 skipped=0 missing=0 failed=0
# Iterate pack/song dirs; read the first .sm/.ssc; extract #BANNER value.
for songdir in "$SONGS_DIR"/*/*/; do
    [ -d "$songdir" ] || continue
    sim=$(find "$songdir" -maxdepth 1 \( -iname '*.ssc' -o -iname '*.sm' \) | head -1)
    [ -n "$sim" ] || continue
    banner=$(grep -m1 -oP '(?<=#BANNER:)[^;]*' "$sim" 2>/dev/null | tr -d '\r' || true)
    case "${banner,,}" in
        *.avi|*.mp4|*.mpg|*.mpeg|*.mkv|*.wmv|*.flv|*.webm) ;;
        *) continue ;;
    esac
    src="$songdir$banner"
    if [ ! -f "$src" ]; then
        echo "  missing video: $src"
        missing=$((missing+1))
        continue
    fi
    pack=$(basename "$(dirname "$songdir")")
    song=$(basename "$songdir")
    # Same mangling as the dashboard's cache_filename(): '/' -> '_'
    dest="$OUT_DIR/Songs_${pack}_${song}_${banner}.png"
    if [ -f "$dest" ]; then
        skipped=$((skipped+1))
        continue
    fi
    if extract_frame "$src" "$dest"; then
        echo "  extracted: $(basename "$dest")"
        extracted=$((extracted+1))
    else
        echo "  FAILED to extract: $src"
        failed=$((failed+1))
    fi
done

echo
echo "Done. extracted=$extracted skipped(already)=$skipped missing-file=$missing failed=$failed -> $OUT_DIR"
echo "Next: copy $OUT_DIR/*.png to the server's dashboard/video-banners/ and rebuild."
