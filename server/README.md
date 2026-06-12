# Server — daily update pipeline

Receives a bundle from the Windows WSL2 client over HTTPS WebDAV, then a
systemd path unit fires the build + deploy. No SSH, no new packages.

## What gets installed where

`install.sh` is a copier — every artifact below is a copy of the repo
version, so re-running it after a repo change re-deploys the updated files.

| Repo source | Installed at | Notes |
|---|---|---|
| `../build_dashboard.py` | `/usr/local/share/sm-dashboard/build_dashboard.py` | Run by sm-update.sh; needs to live where www-data can read |
| `../index.html` | `/usr/local/share/sm-dashboard/index.html` | Copied into the build by `build_dashboard.py` |
| `../nobanner.svg` | `/usr/local/share/sm-dashboard/nobanner.svg` | Same |
| `sm-update.sh` | `/usr/local/bin/sm-update.sh` | systemd ExecStart |
| `sm-update.path` | `/etc/systemd/system/sm-update.path` | PathChanged watcher |
| `sm-update.service` | `/etc/systemd/system/sm-update.service` | Oneshot worker (User=www-data) |
| _(created empty)_ | `/var/www/stepmania-incoming/` | nginx writes uploads here (www-data:www-data 755) |
| _(created empty)_ | `/var/www/stepmania-incoming/.tmp/` | nginx body temp on same FS for atomic rename |
| _(created empty)_ | `/var/www/stepmania-work/` | Build scratch (wiped per run) |
| _(created empty)_ | `/var/www/stepmania-banner-cache/` | Persistent banner-conversion cache (each banner decoded once ever; `$SM_BANNER_CACHE`) |
| `nginx-snippet.conf` | inline-edited into `/etc/nginx/sites-enabled/default` | Auto-inserted right after the existing `/stepmania/` location |

## Prerequisites

- `python3-pil`, `unzip`, nginx with `--with-http_dav_module` — all already
  present on this Ubuntu box (verified during build).
- **Run [`../deploy.sh`](../deploy.sh) first** if you haven't — `install.sh`
  inserts the upload location *after* the `/stepmania/` location that
  `deploy.sh` creates. Without it, `install.sh` aborts with a clear message
  and rolls back.

## First-time install

```bash
sudo bash server/install.sh
```

Then test (in another shell, with basic-auth creds in `~/.netrc`):

```bash
# from anywhere with auth — use any zip with Save/ + Cache/ inside
curl -fsS --netrc -T sm-bundle.zip \
    https://example.com/stepmania-upload/sm-bundle.zip
journalctl -fu sm-update.service
```

Within seconds you should see the extract → build → deploy lines, ending with
`=== update complete ===` and an updated `data.json` size at
`https://example.com/stepmania/data.json`.

## Upgrading (after the dashboard code changes)

**Just re-run `install.sh`.** It's idempotent and covers every file it owns:

```bash
git -C /path/to/dashboard-repo pull          # or however you sync the repo
sudo bash server/install.sh
```

`install` overwrites the installed copies and `systemctl daemon-reload`s the
units. The next upload (or a manual one) uses the new code immediately.

What re-running install.sh **does not** update:

- **The nginx upload block.** Once present, install.sh skips the edit (so
  it doesn't double-insert). If `nginx-snippet.conf` actually changed
  (different `client_max_body_size`, new headers, etc.), you have two
  options:
  1. Edit `/etc/nginx/sites-enabled/default` by hand, replacing the block
     between the `# --- StepMania dashboard upload endpoint` marker and the
     closing brace.
  2. Delete the old block (and the timestamped `.bak.*` it left), then
     re-run `install.sh` so the awk inserter rebuilds it from scratch.
- **`/var/www/stepmania-incoming/` contents.** Stale upload zips (e.g. from a
  failed run) stay until the next successful run deletes them, or you
  `rm /var/www/stepmania-incoming/sm-bundle.zip` manually.

A safe upgrade sequence after touching `sm-update.sh` or `build_dashboard.py`:

```bash
sudo bash server/install.sh
sudo systemctl restart sm-update.path        # picks up the path-unit reload
# trigger a manual update to verify the new code works:
sudo -u www-data /usr/local/bin/sm-update.sh
journalctl -u sm-update.service -n 40 --no-pager
```

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Upload returns `401` | `~/.netrc` missing/wrong on the client; or basic auth misconfigured server-side |
| Upload returns `405` | URL path isn't exactly `/stepmania-upload/sm-bundle.zip` (the only one allowed) |
| Upload returns `413` | `client_max_body_size` in the snippet is smaller than the bundle (default 400m) |
| Upload OK but dashboard doesn't change | `journalctl -u sm-update.service` — usually an "ERROR" line |
| `journalctl` shows "no bundle at /var/www/stepmania-incoming/sm-bundle.zip" | nginx wrote it to the wrong place — check `alias` and `client_body_temp_path` in the snippet |
| `another instance is running` | A previous run still has the flock; usually transient, will fire on the next upload |
| `build failed` | Run the build command manually as www-data to see the Python traceback: `sudo -u www-data python3 /usr/local/share/sm-dashboard/build_dashboard.py /var/www/stepmania-work/extract/Save /tmp/build /var/www/stepmania-work/extract/Cache/Songs` |

## Uninstall

```bash
sudo systemctl disable --now sm-update.path
sudo rm -f /etc/systemd/system/sm-update.{path,service}
sudo rm -rf /usr/local/share/sm-dashboard /usr/local/bin/sm-update.sh
sudo rm -rf /var/www/stepmania-incoming /var/www/stepmania-work /var/www/stepmania-banner-cache
sudo systemctl daemon-reload
# Then remove the /stepmania-upload/ location from /etc/nginx/sites-enabled/default
# (the .bak.* from install.sh has the pre-install copy)
sudo nginx -t && sudo systemctl reload nginx
```
