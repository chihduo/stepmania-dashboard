#!/usr/bin/env bash
#
# The whole local -> GitHub Pages update pipeline in one command:
# build the dashboard from a local StepMania data folder, then publish the
# result to the gh-pages branch (via refresh-demo.sh). For dashboards hosted
# on GitHub Pages instead of your own server — see the README's
# "Hosting on GitHub Pages" section.
#
# Usage:  bash pages-update.sh [STEPMANIA_DATA_DIR]
#
#   STEPMANIA_DATA_DIR  the folder that contains Save/ and Cache/, e.g.
#     installed Windows (WSL):  /mnt/c/Users/You/AppData/Roaming/StepMania 5.1
#     portable install:         the StepMania program folder
#     Linux:                    ~/.stepmania-5.1
#   Defaults to SM_APPDATA from site.env.
#
set -euo pipefail

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Per-machine settings (SM_APPDATA) — env wins over the file.
SITE_ENV="${SITE_ENV:-$DIR/site.env}"
[ -f "$SITE_ENV" ] && { set -a; . "$SITE_ENV"; set +a; }

DATA="${1:-${SM_APPDATA:-}}"
if [ -z "$DATA" ] || [ ! -d "$DATA/Save" ]; then
    red "StepMania data folder not found${DATA:+: $DATA} (needs a Save/ inside)."
    inf "Pass it as the first argument, or set SM_APPDATA in site.env:"
    inf "  bash $0 '/mnt/c/Users/You/AppData/Roaming/StepMania 5.1'"
    inf "  bash $0 ~/.stepmania-5.1"
    exit 1
fi

command -v python3 >/dev/null 2>&1 || { red "python3 not found — install Python 3 first."; exit 1; }

CACHE="$DATA/Cache/Songs"
[ -d "$CACHE" ] || { inf "No Cache/Songs under $DATA — titles/artists will be blank."; CACHE=""; }

inf "Building from: $DATA"
python3 "$DIR/build_dashboard.py" "$DATA/Save" "$DIR/public" "$CACHE"

bash "$DIR/refresh-demo.sh"
