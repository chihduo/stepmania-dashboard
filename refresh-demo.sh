#!/usr/bin/env bash
#
# Refresh the GitHub Pages demo: snapshot the current public/ build onto an
# orphan gh-pages branch and force-push it to origin. See the README's
# "Demo snapshot (GitHub Pages)" section.
#
# Usage:  bash refresh-demo.sh
#
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

[ -f public/index.html ] && [ -f public/data.json ] || {
    echo "public/ incomplete — run: python3 build_dashboard.py" >&2; exit 1; }

WT=$(mktemp -d /tmp/ghp.XXXXXX)
rmdir "$WT"   # git worktree add wants to create it
trap 'git worktree remove --force "$WT" 2>/dev/null || true' EXIT

git worktree add --detach "$WT" HEAD --quiet
(
    cd "$WT"
    git switch --orphan gh-pages-new --quiet
    cp -r "$DIR/public/." .
    touch .nojekyll   # serve files verbatim — no Jekyll pass
    git add -A
    git commit --quiet -m "demo: refresh snapshot ($(date +%F))"
    git branch -M gh-pages-new gh-pages
)
git push -f origin gh-pages

# Pages URL derived from the origin remote (github.com:USER/REPO[.git])
SLUG=$(git remote get-url origin | sed -E 's#^(git@|https://)github\.com[:/]##; s/\.git$//')
echo "Demo pushed. Serves in ~1 min at: https://${SLUG%%/*}.github.io/${SLUG#*/}/"
