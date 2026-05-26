# ftp/ — local archive drop zone

A workflow for refreshing the dashboard from a single archive uploaded to this
folder. Useful if you're shuttling `Save/` + `Cache/` over FTP/SFTP/SMB from
the Windows machine instead of using the WSL pipeline.

## Usage

1. Export `%APPDATA%\StepMania 5.1\{Save,Cache}` from Windows into a single
   archive (any layout — see "Accepted layouts" below).
2. Upload it here as **exactly** one of:

   ```
   StepMania 5.rar
   StepMania 5.zip
   ```

3. Run:

   ```bash
   bash update_from_archive.sh
   ```

4. The script extracts, rebuilds, and cleans up.  When it finishes, push to
   the live site:

   ```bash
   sudo bash ../deploy.sh
   ```

## What the script does

1. Locates the archive in this folder (`.rar` is tried before `.zip`).
2. Verifies the right tool is installed (`unrar` for `.rar`, `unzip` for `.zip`).
   Prints the apt command to install if missing.
3. Extracts into `./extracted/` (transient; wiped on next run, and on success).
4. Finds `Save/` and (optionally) `Cache/Songs/`, `Cache/Banners/` regardless
   of how deeply they're nested — top-level, inside `StepMania 5/`, or up to
   five directory levels in.
5. Runs `../build_dashboard.py` with those paths. Banners auto-detected via
   `SM_BANNERS` env var.
6. Deletes `./extracted/`.

It does **not** deploy to `/var/www/stepmania/` (that needs sudo and is a
separate decision). Run `../deploy.sh` after if you're happy with the result.

It does **not** touch the repo's `../../savedata/` or `../../cachedata/`
directories — those remain the original-`Save.zip`/`Cache.zip` extractions.
The new archive is processed in isolation and only the build output
(`../public/`) is updated.

## Prerequisites

| Archive type | Tool | Install |
|---|---|---|
| `StepMania 5.zip` | `unzip` | already installed |
| `StepMania 5.rar` | `unrar` **or** `rar` | already installed on this server (`rar`); else `sudo apt-get install unrar` |

The build step needs Python 3 + Pillow (`python3-pil`) for banner conversion —
already installed on this server.

## Accepted layouts

The script's `find` accepts any of these. All produce the same result.

```
# Bare
StepMania 5.zip
└── Save/
└── Cache/
    ├── Songs/
    └── Banners/

# Nested in one folder
StepMania 5.zip
└── StepMania 5/
    ├── Save/
    └── Cache/...

# Nested deeper (e.g. zipped from %APPDATA%)
StepMania 5.zip
└── Roaming/
    └── StepMania 5.1/
        ├── Save/
        └── Cache/...
```

If `Save/` isn't found, the script prints the top-level directory listing
of the archive so you can see what went wrong.

## Files in this folder

| File | Tracked in git? |
|---|---|
| `update_from_archive.sh` | yes |
| `README.md` | yes |
| `StepMania 5.rar` / `StepMania 5.zip` | **no** (gitignored — personal data) |
| `extracted/` | **no** (gitignored — transient build scratch) |
