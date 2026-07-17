# StepMania Play-Activity Dashboard

> _Last updated: **2026-07-17** — bump this date whenever you edit this file._
> _Pipeline doc: also see [`server/README.md`](server/README.md) and [`wsl/README.md`](wsl/README.md) for the daily WSL → server update path._
>
> ▶ **[Live demo](https://chihduo.github.io/stepmania-dashboard/)** — static
> snapshot of a real four-year play history (2,200+ songs, 5,200+ logged plays),
> served from the `gh-pages` branch.

A self-contained static dashboard built from a StepMania 5.1 `Save` (and `Cache`)
folder. No server-side code, no CDN — vanilla HTML/JS + hand-rolled SVG charts +
locally-converted PNG banners. Works behind your nginx COEP (`credentialless`)
and offline.

Click any row in **Recent plays** or the **Song ranking** to open a per-song
detail modal: chart difficulty tabs, accuracy + W1% progression with max-combo
bars, lifetime judgment breakdown, hold-note reliability, the song's chart-difficulty profile
(stream/voltage/air/freeze/chaos from the cache), and a table of every recorded
score on that chart. Esc / click outside to close. Use **← / →** (or the
chevrons in the header, or a horizontal swipe on touch) to step to the next /
previous song in the list you opened from (the filtered ranking, or recent
plays — your sort and search are preserved).

### Section anchors

Each major section has a stable `id` so the URL can deep-link straight to it
(e.g. share `…/stepmania/#ranking` to land on the song table). Smooth-scroll
fires on initial load *and* on subsequent in-page hash changes.

| Anchor | Section |
|---|---|
| `#overview` | KPI tiles at the top (totals, streaks, etc.) |
| `#activity` | Activity over time (monthly plays + skill trend, calories, hour-of-day, day-of-week) |
| `#breakdowns` | Plays by difficulty, grades, top artists, top packs |
| `#achievements` | Hardest charts cleared, most-improved songs, trophy case (FCs & MFCs) |
| `#recent-plays` | Recent plays list |
| `#ranking` | Song ranking table (with search, sort + time-window tabs) |

## Files in this directory

| File | Purpose |
|---|---|
| `build_dashboard.py` | Parses Save/Cache → writes `public/data.json` + copies page assets. |
| `config.json` | Portable app config — chart colors, top-N counts, artist aliases, grade thresholds. Committed and shareable; no personal data. |
| `site.env` | Per-machine settings (player name, live dir, server host, local paths). Copy `site.env.example` and edit. |
| `index.html` | The dashboard page (source). |
| `nobanner.svg` | Theme-matching placeholder for songs without a banner. |
| `public/` | **The deployable folder** — `index.html`, `data.json`, `nobanner.svg`, `banners/`. (Gitignored — regenerable.) |
| `deploy.sh` | One-shot: copies `public/` to `/var/www/stepmania/` and adds the nginx `location` block. |
| `.banner-cache/` | Persistent banner-conversion cache — each banner decoded once ever, builds repopulate `public/banners/` by copy. (Gitignored.) |
| `video-banners/` | Banner frames for songs whose `#BANNER` is a video (StepMania never pre-renders those). `wsl/collect-video-banners.sh` extracts PNG frames directly in WSL (ffmpeg) — copy just the PNGs here and rebuild. Staging the raw videos also works as a fallback. (Gitignored.) |
| `server/` | Server-side daily-update pipeline (nginx WebDAV endpoint, systemd path/service units, processing script, installer). |
| `wsl/` | Windows-side tools: daily-update pipeline (WSL2 cron job that bundles + uploads), `collect-video-banners.sh` (extract banner frames from video banners), `add-mv-backgrounds.sh` (generate MV video backgrounds for songs without one). |
| `ftp/` | Local drop folder + script for refreshing the dashboard from a single uploaded archive (`StepMania 5.zip` / `StepMania 5.rar`). Alternative to the WSL pipeline. |
| `README.md` | This file. |

## Data sources (StepMania 5.1, Windows paths)

| Source | What it gives us | Required? |
|---|---|---|
| `…\Save\LocalProfiles\<id>\Stats.xml` **or** `…\Save\MachineProfile\Stats.xml` | Lifetime totals, per-song play counts (`NumTimesPlayed`), difficulty/grade/style breakdowns, per-day calories. A non-empty player profile under `LocalProfiles\` is preferred (the most recently played one wins); the machine profile is the fallback. | **Yes** (one of the two) |
| `%APPDATA%\StepMania 5.1\Save\Upload\*.xml` | Per-play event log with exact timestamps → plays-over-time, hour-of-day, day-of-week, recent plays. Also merged into each chart's score list, since Stats.xml is only flushed periodically and caps its per-chart high-score lists. | Recommended |
| `%APPDATA%\StepMania 5.1\Cache\Songs\*` | Real song `#TITLE`, `#ARTIST`, per-chart `#METER` + `#RADARVALUES` (used by the song-detail modal). Without it, song = folder name, artist = blank, no chart difficulty meters. | Recommended |
| `%APPDATA%\StepMania 5.1\Cache\Banners\*` | Per-song banner thumbnails (StepMania-proprietary ARGB1555 format — converted to PNG by the build). | Optional (placeholder used otherwise) |

The parser tolerates StepMania's occasionally-malformed XML (raw `&`, non-UTF-8
folder names) and matches cache files case-insensitively so `DDR K-POP` (in your
play log) resolves to `DDR K-Pop` (on disk).

### Portable and non-Windows installs

The `%APPDATA%` paths above are the standard installed-on-Windows locations.
The build itself doesn't care where the folders come from — it only needs to be
handed a `Save/` and a `Cache/` folder:

| Install type | Where `Save/` and `Cache/` live |
|---|---|
| **Portable Windows** (a blank `Portable.ini` in the StepMania program folder switches StepMania to portable mode) | Inside the program folder itself: `<StepMania folder>\Save\`, `<StepMania folder>\Cache\` |
| **Linux** | `~/.stepmania-5.1/` (suffix matches the version: `-5.0`, `-5.1`, …) |

Pointing the pipeline at them:

- `build_dashboard.py` takes the Save dir as its 1st argument (and
  `Cache/Songs` as the 3rd) — pass any location directly.
- WSL upload client: set `SM_APPDATA` in `site.env` to the portable program
  folder (e.g. `/mnt/d/Games/StepMania`); the bundler only requires that
  `Save/` and `Cache/` exist inside whatever folder it's given.
- The `ftp/` archive route is location-agnostic by construction — zip your
  `Save/` + `Cache/` from wherever they live.

## Dependencies

- **Python 3** (stdlib only for the basic build)
- **Pillow (PIL)** — needed only for banner conversion:
  `sudo apt-get install python3-pil`  (skip if you don't want banners)
- No JavaScript build step; no runtime deps for the served page.

## Rebuild after new play sessions

1. On Windows, zip and copy these to the build machine: `%APPDATA%\StepMania 5.1\Save`
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

## Configuration

All personal / machine-specific settings live in one file, `site.env`. Set up a
new machine (or someone else's copy) by copying the template and editing it —
that's the only file you touch:

```bash
cp site.env.example site.env
```

| Key | Used for |
|---|---|
| `SM_PLAYER_NAME` | Name shown in the dashboard header (blank = plain title). |
| `SM_LIVE_DIR` | nginx web root the build deploys into (blank = no auto-deploy). |
| `SM_HOST` | Public host of your dashboard server — drives the upload/verify URLs, `~/.netrc` machine, and links. |
| `SM_APPDATA` | (WSL client) Windows `StepMania 5.1` dir; auto-detected if unset. |

`config.json` keeps only portable app config (colors, top-N, artist aliases,
grade thresholds) — safe to commit and share. Any `site.env` key can also be
overridden by an environment variable of the same name at runtime.

### Grades

Each play shows a letter grade. There are two modes:

- **Accuracy-derived (recommended):** define `gradeThresholds` in `config.json` —
  an ordered list of `{ "letter": "...", "min": 0.0–1.0 }` cutoffs. Every play's
  letter is then computed from its accuracy (`PercentDP`), giving one consistent
  scale across **all** your history regardless of which StepMania theme/version
  recorded it. This is the default in the shipped `config.json`; the cutoffs
  there were calibrated against one real play history — where a `PercentDP` of
  ~0.83 was already a solid `AA`, vs the textbook 0.93 — so treat them as a
  starting point and tune them to your own scoring.
- **StepMania's grade (fallback):** delete the whole `gradeThresholds` key and the
  dashboard shows the grade StepMania recorded, mapped to a letter by `GRADE_MAP`
  in `build_dashboard.py`. That map matches the **current default theme's 17-tier
  ladder** (`AAA★, AAA, AA+, AA, AA−, A+, A, A−, B+, B, B−, C+, C, C−, D+, D, D−`,
  read from the theme's grade graphics). A bundle recorded under a *different*
  theme may not line up, since grade tiers are theme-defined — which is exactly
  why the accuracy-derived mode exists.

`Failed → F` and `NoData → −` always, in either mode. "D and below" (plus F) are
the grades hidden from the ranking list and recent plays. One exception: the
**Breakdowns → grades** bar chart uses StepMania's lifetime per-tier stage tally
(an aggregate with no per-play accuracy), so it stays on the tier map even in
accuracy-derived mode.

## Deploy to nginx

The dashboard is served from its own path (`/stepmania/`) under your site,
behind whatever auth the surrounding nginx `server` block already provides.
Point `SM_HOST` (public host) and `SM_LIVE_DIR` (web root) in `site.env` at
your server.

```bash
sudo bash deploy.sh
```

### Deploying without sudo (auto-deploy on every build)

`/var/www/stepmania/` is owned by `www-data` by default, so the deploy needs
sudo. Once, give yourself ownership while keeping group access for nginx:

```bash
sudo chown -R $USER:www-data /var/www/stepmania && \
sudo chmod -R g+w /var/www/stepmania && \
sudo chmod g+s /var/www/stepmania
```

After that:
- `bash deploy.sh` (no sudo) works.
- `python3 build_dashboard.py` **also auto-deploys** at the end whenever the
  live dir (`SM_LIVE_DIR` in `site.env`) is set and writable. There is no
  built-in default: leave `SM_LIVE_DIR` empty and the build skips deploying, and
  `deploy.sh` refuses to run unless `DEST=…` is passed explicitly. So a
  typical change becomes a single command:
  ```bash
  python3 build_dashboard.py     # builds, then auto-deploys live
  ```
  (Browser still needs Ctrl+F5 to defeat the `data.json` cache.)

The future `sm-update.service` (systemd, runs as www-data) still works: the
setgid bit means files it creates inherit the www-data group, so nginx can
read them and you can still delete/replace them.

What `deploy.sh` does:
1. Mirrors `public/` (auto-located next to the script; incl. `banners/` +
   `nobanner.svg`) into `SM_LIVE_DIR` from `site.env`, clearing stale
   banners first; sets `www-data` owner and 644/755 perms. Override either
   side with `SRC=…` / `DEST=…` env vars.
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

URL: `https://<SM_HOST>/stepmania/` (from `site.env`).

## Demo snapshot (GitHub Pages)

The `gh-pages` branch holds a static snapshot of `public/` (plus a `.nojekyll`),
served by GitHub Pages as the live demo linked at the top. The site is fully
static, so the snapshot is the real dashboard, not a mock. To refresh it after
a rebuild:

```bash
git worktree add --detach /tmp/ghp HEAD
cd /tmp/ghp && git switch --orphan gh-pages-new
cp -r "$OLDPWD/public/." . && touch .nojekyll
git add -A && git commit -m "demo: refresh snapshot ($(date +%F))"
git branch -M gh-pages-new gh-pages
cd "$OLDPWD" && git worktree remove --force /tmp/ghp
git push -f origin gh-pages
```

## Daily WSL → server update pipeline

Once the manual setup above is in place, the dashboard refreshes itself
automatically:

```
WSL2 cron @ 05:00 local time
    │  zip /mnt/c/.../StepMania 5.1/{Save,Cache} → sm-bundle.zip
    │  curl --netrc -T sm-bundle.zip https://<SM_HOST>/stepmania-upload/sm-bundle.zip
    ▼
nginx (built-in dav_module)
    │  writes /var/www/stepmania-incoming/sm-bundle.zip
    ▼
systemd sm-update.path  (PathChanged trigger)
    │
    ▼
sm-update.service (User=www-data, flock'd)
       extract → run build_dashboard.py → rsync deploy → cleanup
       a few seconds end-to-end for a ~2,000-song history
```

No exotic server dependencies (`dav_module` is built into stock nginx;
`python3-pil` and `unzip` come from apt). Install with:

```bash
sudo bash server/install.sh    # on the dashboard server
bash wsl/wsl-install.sh        # on the Windows WSL2 box
```

Details, env-var overrides, and the WSL2 cron caveats are in
[`server/`](server/) and [`wsl/README.md`](wsl/README.md).

## Customizing

| Want to… | Where |
|---|---|
| Change chart colors (bars + lines) | `config.json` — edit hex values, rebuild |
| Change how many rows the Top Artists / Top Packs cards show | `config.json` `topN: { artists: 15, packs: 15 }` — defaults to 15 each |
| Force-merge artist name variants (e.g. `소녀시대` → `Girls' Generation`) | `config.json` `artistAliases: { "Canonical": ["variant1", "variant2"] }` — auto-norm already catches casing/punctuation; use this for cross-language merges only |
| Change the grade scale (letters + cutoffs) | `config.json` `gradeThresholds` — see [Grades](#grades). Delete the key to use StepMania's recorded grade instead. |
| Hide more (or fewer) low grades | `grade_hidden()` in `build_dashboard.py` + `gradeHidden()` in `index.html` (default: displayed letter is `F` or starts with `D`) |
| Change banner thumbnail size | `max_w=160` in `convert_banner()` |
| Add banners to the ranking table too | call `banner(s["dir"])` per song in `parse_stats` and render in the table |
| Prefer romanized titles | swap `tag(text, "TITLE")` and `tag(text, "TITLETRANSLIT")` order in `make_meta_lookup` |
| Adjust recent-plays count | `recent[:150]` in `parse_uploads` (also bump the renderer's `slice(0,30)` cap in `index.html`) |
| Change the ranking window tabs | `WINDOW_SPANS = (7, 30, 90, 180, 365)` (days) in `build_dashboard.py`; tab labels in `WIN_LABELS` in `index.html` |

## Notes / gotchas

- **Grade letters** are either derived from accuracy (`gradeThresholds` in
  `config.json`) or mapped from StepMania's recorded tier (`GRADE_MAP` in
  `build_dashboard.py`, exposed to JS as `gradeMap`). See [Grades](#grades).
  `grade_letter()` (Python) and `displayGrade()` (`index.html`) implement the
  same two-mode logic; keep them in sync.
- **"Songs played"** counts every stage including retries; **"Distinct songs"**
  counts unique charts with ≥1 play.
- Theme-internal placeholder `Themes/default/Other/` is excluded from the
  ranking (it's not a real song).
- **Ranking window tabs:** the song ranking has tabs for the last
  7/30/90/180 days and 12 months (plus All time); **7 days** is the default
  tab (All time when the bundle has no Upload log). Windows are computed from the
  per-play Upload log and are **anchored at the last recorded play**, not at
  "today" — so a break from the game never empties a tab; you're always looking
  at your most recent N days *of activity* (the caption shows the exact date
  range). In a window tab the Plays column reads `window / lifetime` and songs
  with no plays in the window are omitted. Bundles without an Upload log get no
  tabs (All time only, from Stats.xml aggregates). Best % / Grade / Last played
  stay lifetime values in every tab.
- **D/F filter:** songs whose *best* displayed grade is D-and-below or F are
  hidden from the ranking list and recent plays. KPI totals, timeline and
  breakdown charts still reflect all plays. The test is letter-based (so it
  works in either grade mode): `gradeHidden()` for the ranking (client-side, so
  the modal can still open) and `grade_hidden()` for the recent feed.
- **`charts` array per song in `data.json`:** each song carries a `charts`
  list with per-difficulty meter, radar profile, and the full HighScore
  records that StepMania kept (typically up to ~10-20 per chart, the best
  ones). The modal renders from these; the ranking table only needs the
  song-level aggregates.
- **Banner cache is not actually PNG/JPG** despite the `.png` extension — it's
  a 32-byte StepMania `SurfaceHeader` (8 LE uint32s: w/h/pitch/RGBA-masks/bpp)
  followed by raw pixels. The current build handles 16-bit ARGB1555 (the only
  variant observed in real caches so far). If you see `decode-fail` > 0 after a
  cache refresh, that's a new bpp/mask combo to add to `convert_banner`.
- **Songs whose on-disk folder names contain non-UTF-8 bytes** can't be matched
  to their cache entries, so their artist/title/banner stay blank (the plays
  still count). Rare — typically packs that went through a broken zip tool.
