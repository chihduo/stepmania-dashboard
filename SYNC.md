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
- `banners/<sha256(png)>.json`: a `png_base64` envelope containing a small PNG.

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

Every rebuild reads the current live `data.json` and compares profile identity,
lifetime totals, per-song play counts, and daily/monthly play-log counts. A decrease
fails the job and leaves the live site intact. The first upload therefore needs
the complete matching profile and `Save/Upload` history. A different or reset
profile must be migrated deliberately; the upload workflow does not replace it
silently. If the original data is unavailable, keep the existing site and restore
the matching Save backup before retrying. Missing song metadata/thumbnails can
fall back to the published site. Static HTML cannot reconstruct missing play logs.

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
