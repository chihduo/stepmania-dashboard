# WSL2 — daily upload pipeline

The Windows StepMania machine runs WSL2 Ubuntu. Once per day, a cron job
inside WSL zips `%APPDATA%\StepMania 5.1\{Save,Cache}` (read via `/mnt/c`) and
PUTs the bundle to the dashboard server's WebDAV endpoint. The server (see
`../server/`) does all the heavy lifting (extract, build, deploy).

## One-time setup

```bash
git clone <this-repo> ~/sm-dashboard       # or however you got the repo here
cd ~/sm-dashboard
bash wsl/wsl-install.sh
```

The installer:
1. apt-installs `zip curl cron`
2. Copies `wsl-update.sh` to `~/.local/bin/`
3. Prompts for the class basic-auth creds and writes them to `~/.netrc`
   (chmod 600 — required by curl, never logged)
4. Adds a `0 5 * * * ~/.local/bin/wsl-update.sh` crontab line (with confirmation)
5. Starts the cron service in the current session

## Daily run

`wsl-update.sh` does:
1. Auto-detects `/mnt/c/Users/<you>/AppData/Roaming/StepMania 5.1/`
2. `zip -qr sm-bundle.zip Save Cache` (~70 MB Save + ~250 MB Cache → ~300 MB)
3. `curl --netrc -T sm-bundle.zip https://example.com/stepmania-upload/sm-bundle.zip`
4. Waits 30 s, HEADs `/stepmania/data.json`, logs `Last-Modified` + size
5. Cleans up its temp dir

Logs land in `~/.local/share/sm-update/wsl-update.log` (one line per step,
timestamped). Inspect with `tail ~/.local/share/sm-update/wsl-update.log`.

## WSL2 cron caveats (read this!)

WSL2 shuts down the VM when no terminal is open. **Cron won't fire if WSL
is asleep.** Two ways to handle:

### (A) Keep WSL alive — cron-driven
In `%UserProfile%\.wslconfig` on Windows:
```
[wsl2]
vmIdleTimeout=-1
```
And in `/etc/wsl.conf` inside WSL:
```
[boot]
systemd=true
```
Then `wsl --shutdown` in PowerShell, reopen WSL, and
`sudo systemctl enable --now cron`.

### (B) Windows Task Scheduler — schedule-driven (recommended)
Create a daily Task that runs at 05:00:
```
Program:    wsl.exe
Arguments:  -d Ubuntu -u <you> bash -lc '~/.local/bin/wsl-update.sh'
```
This wakes WSL on schedule, runs once, lets it idle out. Doesn't need cron
inside WSL — but the script is harmless to run either way, so you can keep
the crontab line as a fallback.

## Overrides

| Env var | Purpose | Default |
|---|---|---|
| `APPDATA` | Path to `StepMania 5.1` dir | Auto-detected under `/mnt/c/Users/*/AppData/Roaming/` |
| `URL` | Upload endpoint | `https://example.com/stepmania-upload/sm-bundle.zip` |
| `VERIFY_URL` | URL to HEAD after upload | `https://example.com/stepmania/data.json` |

## Troubleshooting

- **`401 Unauthorized`** → `~/.netrc` missing or wrong host; re-run installer.
- **`413 Request Entity Too Large`** → server's `client_max_body_size` < bundle
  size; the server install sets 400 MB. Check `/etc/nginx/sites-enabled/default`.
- **Upload succeeds but dashboard doesn't change** → `journalctl -u sm-update`
  on the server. Likely a bundle structure issue (no `Save/` at expected nesting).
- **`Connection timed out`** → bump curl `--max-time` in `wsl-update.sh`
  (default 1800 s = 30 min, enough for ~300 MB on a 1.3 Mbps upload).
