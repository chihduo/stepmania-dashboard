# Upload from StepMania 6

The game uploads only when the player selects **Upload Statistics** on the title
menu. It needs no Python, Git, WSL or GitHub CLI installation on Windows.
Python runs in GitHub Actions, and GitHub Pages hosts the generated site.

## Repository setup

The workflow `.github/workflows/dashboard-sync.yml` must be on the default branch.
Use GitHub Actions as the Pages publishing source. For this existing site, first
run the workflow with `operation=bootstrap`; it republishes the current `gh-pages`
files without changing their data. Keep that branch as a rollback snapshot.
The default branch contains trusted builder code, while `dashboard-data` holds
only uploaded statistics. To change the latter, set the `DASHBOARD_DATA_BRANCH`
repository variable and the matching game preference.

Use a fine-grained personal access token with access to **this repository only**
and **Contents: read and write**. The game stores it in Windows Credential Manager.
The workflow uses its own short-lived token for Pages deployment. No personal
token goes into Actions secrets, source files, logs or exported statistics.

## Export version 1

Paths on the data branch:

- `profiles/<guid>/manifest.json`: version, explicit profile GUID/kind and event count.
- `profiles/<guid>/Stats.xml`: allowlisted cumulative profile statistics.
- `profiles/<guid>/events/<sha256(play-guid)>.xml`: one immutable play per file.
- `profiles/<guid>/songs/<sha256(song-dir)>.json`: title, artist, chart data and banner reference.
- `profiles/<guid>/packs/<sha256(pack-dir)>.json` optionally supplies a shared image for the exact pack directory. Its fields are `dir` and `banner`.
- `banners/<sha256(png)>.json`: a `png_base64` envelope containing a small PNG.

The numeric difficulty rating (chart meter) is separate from a chart's difficulty
label and play history. The dashboard accepts ratings from 0 through 1000. If an
integer falls outside that range, the builder keeps a previously published
rating for the same chart when it can match it uniquely. Otherwise the rating
is left blank. The chart, its scores, and its artwork still publish.

Banner envelopes allow many images to share one Git tree API request instead of
requiring one GitHub write request per image. Actions verifies and decodes them
into ordinary `public/banners/<hash>.png` files. Existing PNG files with the same
names are also accepted. Files are compared by Git blob hash, so unchanged data
and images are not retransmitted. Removed local songs retain remote events and
metadata. No song audio, movies, full chart note data or raw configuration is sent.

An accepted upload is one fast-forward commit. Partial tree/blob uploads do not
change the branch. Ref conflicts are retried against the current tree, and the
publication dispatch can be retried after an accepted commit. The workflow runs
trusted code from the default branch, validates the requested revision's ancestry,
and builds the latest complete data tree. Serial deployment prevents concurrent
runs from replacing a newer site with an older snapshot.

`sync_dashboard.py` validates the export and reuses `build_dashboard.py` for all
statistics and presentation calculations. It rejects wrong-profile plays, invalid
paths, symlinks, unexpected XML fields, corrupt banners, and incomplete exports.
Only new/changed fields are sent; cumulative totals are never added repeatedly.
Legacy records without IDs receive deterministic IDs from their sanitized content.
Existing GUIDs are preserved, and identical score values with different GUIDs count
as separate plays. Indistinguishable legacy records without any ID are treated as
one event.

## History preservation

Every rebuild reads the current live `data.json` and checks profile identity,
profile-wide lifetime totals, and daily/monthly play-log counts. Wrong profiles,
decreased overall totals, missing songs/charts, and incomplete logs fail the job
and leave the live site intact. Event IDs already present in published score
records must still exist in the upload with the same song, chart and score; new
plays on the same day cannot conceal the removal of those events. The first
upload therefore needs the complete matching profile and `Save/Upload` history.

Per-chart attempt counters and retained high-score lists need different handling.
StepMania increments a chart's counter when a song starts, and a live export can
contain attempts not yet persisted in the local profile. It also trims retained
high-score lists. After checking the uploaded history, the importer keeps the
highest published chart counts and unions the previously published score records
with the current records. Known event IDs stay distinct; matching legacy scores
are paired once, so retries do not duplicate them. Pack and artist counts use the
same preserved song totals. The workflow log and `sync-status.json` report which
counters and scores were retained. This does not edit the game's local profile or
create fabricated play-log events.

A different or reset profile must still be migrated deliberately. Missing song
metadata/thumbnails can fall back to the published site. Details that were never
saved or published cannot be reconstructed from a play counter. If several custom
charts share an indistinguishable identity and their history needs recovery, the
importer rejects the ambiguous merge instead of assigning scores to a guessed
chart.

The old local/server scripts continue to work. Once Actions owns publication, avoid
running `refresh-demo.sh` against the live site: it uses the older branch deployment
method. The retained `gh-pages` branch is the migration baseline/rollback copy.

## Validate locally

```sh
python3 -m pip install Pillow==11.3.0
python3 -m unittest discover -s tests
python3 sync_dashboard.py /path/to/export PROFILE_GUID public --baseline /path/to/old-site
```

The baseline directory contains `data.json` and any thumbnails needed for fallback.
The game keeps its export under `Save/Dashboard/outbox/`. To troubleshoot a rejected
upload, open the workflow log. Repair the missing data locally and select the game
menu option again. A workflow failure never means the local scores were deleted.

## Temporary publication failures

An upload may already be accepted on `dashboard-data` when the publication job
fails to download the current Pages history or a retained song banner. The
baseline downloader retries temporary HTTP errors (408, 429, 500, 502, 503 and
504), timeouts and interrupted connections up to five attempts. Delays increase
between attempts; a server's Retry-After value is used up to a 30-second limit.
Retry messages identify the affected URL.

Missing/forbidden files and oversized responses still fail immediately. If all
attempts fail, the workflow stops before building or deploying; it does not omit
the missing banner or bypass history validation. The current dashboard stays
online. Select **Upload / Retry** after the temporary service problem clears to
retry publication without duplicating plays. This server-side recovery requires
no Windows executable update or changes to local profile/log files.

## Legacy saves and rejected uploads

Cumulative profiles can contain calibration scores under
`Themes/<theme>/Other/`. These entries are accepted in Stats.xml and excluded
from song rankings, as in the original builder; lifetime totals remain unchanged.
Normal song metadata and per-play events still require relative `Songs/` paths.

An **incomplete historical play logs** error reports the uploaded and published
counts. It can mean old `Save/Upload` files are missing or that the game filtered
them. For a local-profile upload, the game accepts only records whose PlayerGuid
matches the selected profile; older records with empty PlayerGuid are also
excluded. Check `skipped_other_profiles` in `Save/Dashboard/pending.json` and the
PlayerGuid field in an older local upload XML. Retain the originals. Restoring
files alone will not resolve a player-ID mismatch, and switching to the machine
profile would fail the published dashboard's profile-identity check.

For an owner-confirmed migration from machine to named profile, a backed-up
repair can assign blank PlayerGuid fields in the old logs to the named profile's
GeneralData/Guid. The separate HighScore/Guid identifies the individual play and
must stay unique and unchanged, along with StageGuid, dates, and scores. This
works with the existing exporter and strict importer without a new preference.
Merge the repaired files into Save/Upload and use Upload/Retry. The existing
dashboard remains online until the repaired export passes preservation checks.

## Missing song banners

Use a current StepMania 6 executable, keep the affected song packs installed,
and choose **Upload Statistics**. For every installed song in the selected
profile's history, the game checks the dedicated banner, then a jacket or still
background. For a movie banner it can export a single PNG frame. The game and
dashboard support the `Songs` and `AdditionalSongs` libraries.

If no song artwork is available, the importer can share one pack banner across
songs and recent plays with the same pack directory. A previously published
song image has priority over a pack image. A later upload can replace a shared
pack image with the song's own artwork. Older uploads without pack records
continue to use the existing song images and baseline.

In the game, the status distinguishes missing artwork from unavailable song
folders and reports the number of new image files accepted. For individual
songs see `Save/Dashboard/artwork-report.json` on the uploading PC. Preserve
`Save/Dashboard/outbox` when updating. The manual builder also reads the native
`Cache/Banner` directory and older bundles staged under `Cache/Banners`.
