#!/usr/bin/env bash
#
# One-time setup for the daily WSL2 → dashboard upload pipeline.
#
#   bash wsl/wsl-install.sh
#
# What it does:
#   1. apt-installs dependencies: zip, curl, cron (sudo prompt)
#   2. Installs wsl-update.sh -> ~/.local/bin/
#   3. Writes basic-auth creds to ~/.netrc (chmod 600) — prompts for creds
#   4. Adds a daily 05:00 crontab line (with confirmation)
#   5. Starts the cron service in this WSL session
#   6. Prints WSL-specific caveats about cron + idle shutdown
#
set -euo pipefail

[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user (no sudo)."; exit 1; }
[ -d /mnt/c ]      || { echo "This script must run inside WSL2 (no /mnt/c found)."; exit 1; }

REPO=$(cd "$(dirname "$0")/.." && pwd)

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
grn(){ printf '\033[32m%s\033[0m\n' "$*"; }
inf(){ printf '\033[36m%s\033[0m\n' "$*"; }

# 1. Dependencies ----------------------------------------------------------
inf "Installing apt deps (zip curl cron) — sudo prompt incoming"
sudo apt-get update -qq
sudo apt-get install -y zip curl cron

# 2. Script ---------------------------------------------------------------
inf "Installing wsl-update.sh -> ~/.local/bin/"
install -d "$HOME/.local/bin"
install -m 755 "$REPO/wsl/wsl-update.sh" "$HOME/.local/bin/wsl-update.sh"

# 3. ~/.netrc credentials -------------------------------------------------
HOST="example.com"
NETRC="$HOME/.netrc"
if [ -f "$NETRC" ] && grep -q "machine $HOST" "$NETRC"; then
    grn "~/.netrc already has an entry for $HOST — skipping credential setup."
else
    echo
    echo "Basic-auth credentials for $HOST (the class login):"
    read -rp "  username: " AUTH_USER
    read -rsp "  password: " AUTH_PASS; echo
    {
        [ -f "$NETRC" ] && cat "$NETRC"
        echo "machine $HOST login $AUTH_USER password $AUTH_PASS"
    } > "$NETRC.tmp"
    mv "$NETRC.tmp" "$NETRC"
    chmod 600 "$NETRC"
    grn "Wrote credentials to $NETRC (chmod 600)."
fi

# 4. crontab --------------------------------------------------------------
LINE="0 5 * * * \$HOME/.local/bin/wsl-update.sh"
echo
echo "Proposed crontab entry (daily 05:00 WSL local time):"
echo "  $LINE"
read -rp "Install it? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
    (crontab -l 2>/dev/null | grep -v 'wsl-update\.sh' ; echo "$LINE") | crontab -
    grn "Crontab updated. Current jobs:"
    crontab -l
fi

# 5. Start cron in this session ------------------------------------------
if ! pgrep -x cron >/dev/null; then
    inf "Starting cron service in this WSL session"
    sudo service cron start || true
fi

# 6. Caveats -------------------------------------------------------------
cat <<'EOF'

============================================================================
IMPORTANT — WSL2 cron caveats:

WSL2 shuts down the VM when no terminal is open (idle timeout, default 8s).
Cron won't fire at 05:00 if WSL is asleep. Two ways to fix this:

(A) Keep WSL alive longer.  In %UserProfile%\.wslconfig on Windows:
      [wsl2]
      vmIdleTimeout=-1        # never auto-shutdown
    Then enable systemd-managed cron in WSL — add to /etc/wsl.conf:
      [boot]
      systemd=true
    and: 'wsl --shutdown' (PowerShell), reopen, 'sudo systemctl enable --now cron'

(B) Drive it from Windows Task Scheduler (more reliable for a daily job).
    Create a Basic Task at 05:00 that runs:
      wsl.exe -d Ubuntu -u <you> bash -lc '~/.local/bin/wsl-update.sh'
    This wakes WSL on schedule, runs once, lets it idle out again.
    No cron needed inside WSL.

Logs (whichever path you choose):
  ~/.local/share/sm-update/wsl-update.log

Test the upload right now:
  ~/.local/bin/wsl-update.sh
  tail ~/.local/share/sm-update/wsl-update.log
============================================================================
EOF
