# WSL2 — daily upload pipeline & song-library tools

> _Last updated: **2026-07-17** — bump this date whenever you edit this file._

The Windows StepMania machine runs WSL2 Ubuntu. Once per day, a cron job
inside WSL zips `%APPDATA%\StepMania 5.1\{Save,Cache}` (read via `/mnt/c`) and
PUTs the bundle to the dashboard server's WebDAV endpoint. The server (see
`../server/`) does all the heavy lifting (extract, build, deploy).

> No server? There's a serverless alternative to this whole pipeline: build
> locally and host on GitHub Pages with `../pages-update.sh` — see
> ["Hosting on GitHub Pages"](../README.md#hosting-on-github-pages) in the
> root README.

This folder also holds two **one-shot song-library tools** (run manually in
WSL where the `Songs/` library lives — not part of the daily pipeline):

| Script | Purpose |
|---|---|
| `collect-video-banners.sh` | For songs whose `#BANNER` is a video (StepMania never pre-renders those into `Cache/Banners`): extracts one PNG frame per video with ffmpeg. Takes your `Songs/` folder as a **required** first argument. Copy the PNGs to the server's `dashboard/video-banners/` and rebuild — those songs then get real banners on the dashboard. |
| `add-mv-backgrounds.sh` | For songs with no gameplay background video: searches YouTube for the song's MV (yt-dlp), trims to chart length with a 2s fade-out, encodes to SM5-compatible H.264, and wires it into the `.sm` (`#BGCHANGES`; original backed up to `.sm.mvbak`). Rejects too-short or static-image candidates, retries without the artist name after 3 rejections; supports `--dry-run`, `--limit N`, and `--fix` (resume / upgrade videos from older script versions). Needs `ffmpeg` + `yt-dlp` in WSL. |

Both script headers document full usage; `add-mv-backgrounds.sh` additionally
has env-var knobs (`MAX_H`, `N_CAND`, `MAX_SCAN`, `MIN_MOTION`).

## One-time setup

```bash
git clone <this-repo> ~/sm-dashboard       # or however you got the repo here
cd ~/sm-dashboard
cp site.env.example site.env                # then set SM_HOST (see the file)
bash wsl/wsl-install.sh
```

The installer:
1. apt-installs `zip curl cron`
2. Copies `wsl-update.sh` to `~/.local/bin/` and `site.env` to `~/.config/sm-dashboard/`
3. Prompts for your dashboard server's basic-auth login and writes it to `~/.netrc`
   (chmod 600 — required by curl, never logged)
4. Adds a `0 5 * * * ~/.local/bin/wsl-update.sh` crontab line (with confirmation)
5. Starts the cron service in the current session

## Daily run

`wsl-update.sh` does:
1. Auto-detects `/mnt/c/Users/<you>/AppData/Roaming/StepMania 5.1/`
2. `zip -qr sm-bundle.zip Save Cache` (~70 MB Save + ~250 MB Cache → ~300 MB)
3. `curl --netrc -T sm-bundle.zip https://<SM_HOST>/stepmania-upload/sm-bundle.zip`
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

## Upgrading (after the dashboard code changes)

**Re-run `wsl-install.sh`.** It's idempotent:

```bash
cd ~/sm-dashboard
git pull                       # or however you sync the repo
bash wsl/wsl-install.sh
```

It re-copies `wsl-update.sh` to `~/.local/bin/`, skips re-prompting for
credentials if `~/.netrc` already has the host, and skips re-adding the
crontab line if it's already there. **The cron schedule and credentials stay
intact.**

If you only changed `wsl-update.sh` (the daily script itself), you can shortcut
that with one command — no install needed:
```bash
install -m 755 ~/sm-dashboard/wsl/wsl-update.sh ~/.local/bin/wsl-update.sh
```

The server-side build is independent of this script — any new stats or
dashboard features land via re-running the server's `install.sh`, not this one.

## Overrides

Defaults come from `site.env` (see [`../site.env.example`](../site.env.example));
an env var of the same name overrides the file for a one-off run.

| Env var | Purpose | Default |
|---|---|---|
| `SM_HOST` | Dashboard server host (drives the URLs below) | From `site.env` |
| `SM_APPDATA` / `APPDATA` | Folder holding `Save/` + `Cache/` (for a portable install: the StepMania program folder) | `SM_APPDATA` from `site.env`, else auto-detected under `/mnt/c/Users/*/AppData/Roaming/` |
| `URL` | Upload endpoint | `https://$SM_HOST/stepmania-upload/sm-bundle.zip` |
| `VERIFY_URL` | URL to HEAD after upload | `https://$SM_HOST/stepmania/data.json` |

## Troubleshooting

- **`401 Unauthorized`** → `~/.netrc` missing or wrong host; re-run installer.
- **`413 Request Entity Too Large`** → server's `client_max_body_size` < bundle
  size; the server install sets 400 MB. Check `/etc/nginx/sites-enabled/default`.
- **Upload succeeds but dashboard doesn't change** → `journalctl -u sm-update`
  on the server. Likely a bundle structure issue (no `Save/` at expected nesting).
- **`Connection timed out`** → bump curl `--max-time` in `wsl-update.sh`
  (default 1800 s = 30 min, enough for ~300 MB on a 1.3 Mbps upload).
