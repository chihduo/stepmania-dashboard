# StepMania Play-Activity Dashboard

> _Last updated: **2026-05-26** — bump this date whenever you edit this file._

A self-contained static dashboard built from a StepMania 5.1 `Save` (and `Cache`)
folder. No server-side code, no CDN — vanilla HTML/JS + hand-rolled SVG charts +
locally-converted PNG banners. Works behind your nginx COEP (`credentialless`)
and offline.

## Files in this directory

| File | Purpose |
|---|---|
| `build_dashboard.py` | Parses Save/Cache → writes `public/data.json` + copies page assets. |
| `index.html` | The dashboard page (source). |
| `nobanner.svg` | Theme-matching placeholder for songs without a banner. |
| `public/` | **The deployable folder** — `index.html`, `data.json`, `nobanner.svg`, `banners/`. (Gitignored — regenerable.) |
| `deploy.sh` | One-shot: copies `public/` to `/var/www/stepmania/` and adds the nginx `location` block. |
| `README.md` | This file. |

## Data sources (StepMania 5.1, Windows paths)

| Source | What it gives us | Required? |
|---|---|---|
| `%APPDATA%\StepMania 5.1\Save\MachineProfile\Stats.xml` | Lifetime totals, per-song play counts (`NumTimesPlayed`), difficulty/grade/style breakdowns, per-day calories. | **Yes** |
| `%APPDATA%\StepMania 5.1\Save\Upload\*.xml` | Per-play event log with exact timestamps → plays-over-time, hour-of-day, day-of-week, recent plays. | Recommended |
| `%APPDATA%\StepMania 5.1\Cache\Songs\*` | Real song `#TITLE` and `#ARTIST` (SSC format). Without it, song = folder name, artist = blank. | Recommended |
| `%APPDATA%\StepMania 5.1\Cache\Banners\*` | Per-song banner thumbnails (StepMania-proprietary ARGB1555 format — converted to PNG by the build). | Optional (placeholder used otherwise) |

The parser tolerates StepMania's occasionally-malformed XML (raw `&`, non-UTF-8
folder names) and matches cache files case-insensitively so `DDR K-POP` (in your
play log) resolves to `DDR K-Pop` (on disk).

## Dependencies

- **Python 3** (stdlib only for the basic build)
- **Pillow (PIL)** — needed only for banner conversion:
  `sudo apt-get install python3-pil`  (skip if you don't want banners)
- No JavaScript build step; no runtime deps for the served page.

## Rebuild after new play sessions

1. On Windows, zip and copy these to this machine: `%APPDATA%\StepMania 5.1\Save`
   and `%APPDATA%\StepMania 5.1\Cache`.
2. Extract to `../savedata/Save` and `../cachedata/Cache/{Songs,Banners}`
   (the defaults the builder looks for).
3. Run:
   ```bash
   python3 build_dashboard.py                          # uses defaults
   # or, explicitly:
   python3 build_dashboard.py /path/to/Save ./public /path/to/Cache/Songs
   # banners cache is auto-discovered next to Cache/Songs, or override:
   SM_BANNERS=/path/to/Cache/Banners python3 build_dashboard.py ...
   ```
4. Deploy (below). For trivial content changes (no new files), Ctrl+F5 in the
   browser to defeat the `data.json` cache.

The build prints match rates so you can spot regressions:
```
artist/title matched for 2016/2018 songs (100%)
banners converted for recent plays: 112/127 (miss=15, decode-fail=0)
```

## Deploy to nginx

Site root: `/var/www/html/example-site/` (→ `_example-site/_output`), behind basic auth.
The dashboard lives at a dedicated path (`/stepmania/`) so it survives
class-site rebuilds.

```bash
sudo bash deploy.sh
```

What `deploy.sh` does:
1. Mirrors `public/` (incl. `banners/` + `nobanner.svg`) into
   `/var/www/stepmania/`, clearing stale banners first; sets `www-data` owner
   and 644/755 perms.
2. If absent, adds this block to `/etc/nginx/sites-enabled/default` (basic auth
   is inherited from the surrounding `server` block):
   ```nginx
   location ^~ /stepmania/ {
       alias /var/www/stepmania/;
       index index.html;
   }
   ```
3. Backs up the nginx config with a timestamped `.bak.*`, runs `nginx -t`,
   reloads. Rolls back on any failure. Idempotent — safe to re-run.

URL: `https://example.com/stepmania/`

## Customizing

| Want to… | Where |
|---|---|
| Hide more (or fewer) low grades | `EXCLUDE_GRADES = {"Tier07", "Failed"}` in `build_dashboard.py` |
| Change banner thumbnail size | `max_w=160` in `convert_banner()` |
| Add banners to the ranking table too | call `banner(s["dir"])` per song in `parse_stats` and render in the table |
| Prefer romanized titles | swap `tag(text, "TITLE")` and `tag(text, "TITLETRANSLIT")` order in `make_meta_lookup` |
| Adjust recent-plays count | `recent[:150]` in `parse_uploads` (also bump the renderer's `slice(0,30)` cap in `index.html`) |

## Notes / gotchas

- **Grade letters** (AAAA…F) are an approximate mapping of StepMania's
  `Tier01`–`Tier07` and depend on your theme. The map lives in
  `GRADE_MAP` (`build_dashboard.py`) and `gradeMap` (passed to JS).
- **"Songs played"** counts every stage including retries; **"Distinct songs"**
  counts unique charts with ≥1 play.
- Theme-internal placeholder `Themes/default/Other/` is excluded from the
  ranking (it's not a real song).
- **D/F filter:** songs whose *best* grade is D or F are hidden from the
  ranking list and recent plays. KPI totals, timeline and breakdown charts
  still reflect all plays.
- **Banner cache is not actually PNG/JPG** despite the `.png` extension — it's
  a 32-byte StepMania `SurfaceHeader` (8 LE uint32s: w/h/pitch/RGBA-masks/bpp)
  followed by raw pixels. The current build handles 16-bit ARGB1555 (the only
  variant present in this user's cache). If you see `decode-fail` > 0 after a
  cache refresh, that's a new bpp/mask combo to add to `convert_banner`.
- **Two songs are unrecoverable** in this dataset: their on-disk folder names
  contain non-UTF-8 bytes (`E�MO�TION`, `Ao-no-Exorcist-…-�GP���t`), so
  artist/title/banner stay blank. 8 total plays affected.
