# StepMania Play-Activity Dashboard

A self-contained static dashboard built from a StepMania 5.1 `Save` folder.
No server-side code, no external/CDN assets — just `index.html` + `data.json`,
so it works behind your nginx COEP (`credentialless`) and offline.

## Files
- `build_dashboard.py` — parses the Save data → `public/data.json`, copies the page.
- `index.html` — the dashboard (vanilla JS, hand-rolled SVG charts).
- `public/` — **the deployable folder** (`index.html` + `data.json`).

## Data sources (StepMania 5.1)
- `Save/MachineProfile/Stats.xml` → lifetime totals, per-song play counts
  (`NumTimesPlayed`), difficulty/grade/style breakdowns, per-day calories.
- `Save/Upload/*.xml` → per-play event log (exact timestamps) → plays-over-time,
  hour-of-day, day-of-week, recent plays.

## Rebuild after new play sessions
1. Copy the fresh `Save` folder from Windows
   (`%APPDATA%\StepMania 5.1\Save`) onto this machine.
2. Point the builder at it:
   ```bash
   python3 build_dashboard.py /path/to/Save ./public
   ```
   (defaults: `../savedata/Save` → `./public`)
3. Re-copy `public/` to the web root (see deploy below).

The parser tolerates StepMania's occasionally-malformed XML (raw `&`,
non-UTF-8 folder names).

## Deploy to nginx
The site root is `/var/www/html/example-site/` (→ `_example-site/_output`), behind basic auth.

```bash
sudo bash deploy.sh
```

`deploy.sh` copies the files to `/var/www/stepmania/`, then adds a
`location ^~ /stepmania/` block to `/etc/nginx/sites-enabled/default`
(with a timestamped backup), runs `nginx -t`, and reloads — rolling back the
config if the test fails. It's idempotent (safe to re-run) and the `^~` makes
the path win over the existing `index.html` regex location; basic auth is
inherited so it stays private.
Visit: `https://example.com/stepmania/`

## Notes
- Grade letters (AAAA…F) are an approximate mapping of StepMania's `Tier01`–`Tier07`
  and depend on your theme.
- "Songs played" counts every stage (incl. retries); "Distinct songs" counts
  unique charts with ≥1 play.
- Theme-internal placeholder `Themes/default/Other/` is excluded from the ranking.
