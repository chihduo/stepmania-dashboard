# Manual upload progress

- [x] Define the allowlisted version 1 XML/metadata/banner export.
- [x] Reuse the dashboard builder with injected song/banner metadata.
- [x] Preserve event GUIDs and deduplicate retries without dropping distinct same-time plays.
- [x] Reject missing historical totals, song counts, and daily/monthly play history.
- [x] Add trusted-code Actions dispatch, serial Pages publishing and an unchanged-site bootstrap.
- [x] Pass nine importer tests and workflow YAML parsing locally.
- [x] Verify the engine-generated export against this importer.
- [x] Publish workflows, run hosted checks, and bootstrap the current live site.
- [ ] Complete the first successful Windows publication after the user installs the repaired logs and selects Upload/Retry.

Hosted importer tests pass (run 43249599943), and the native C++ export passes through the Python importer. The live data matches the retained gh-pages snapshot byte-for-byte (SHA-256 b8a95cf6889675a436b622dddaeedace6106b95040dd2e97b15c45f8a9a98bed; 7,131 lifetime plays). Added main to the Pages environment and switched publishing to Actions. Bootstrap run 43251375360 succeeded. All 1,356 website assets, including 1,353 banners, match the previous snapshot exactly; four live banner URLs and the live data.json also match. The obsolete .nojekyll marker is unnecessary with the Actions deployment.
The existing public site was republished unchanged; no new personal play records or raw Save files were uploaded. The native engine export has also been imported end to end with a real generated PNG banner, song metadata, profile/event records, ampersands and Unicode text.

## First Windows upload repair (2026-11-14)

Plan: reproduce the rejected export against the unchanged live baseline; accept
safe theme calibration entries in cumulative profiles; retain history protection
with actionable diagnostics; add regression tests and publish the reviewed fix.
Investigate the native song lookup separately, without a Windows build.

- [x] Reproduce failed run 43470498036 using uploaded revision 27a1d0ea34ac2eda56ba72950837e9860f38aad7.
- [x] Identify the rejected calibration entry, `Themes/default/Other/`, and the
  builder's existing exclusion of theme-internal entries from song lists.
- [x] Confirm the live baseline is unchanged: 7,131 lifetime plays and 5,918
  per-play logs. The upload has 7,249 lifetime plays but only 827 per-play logs,
  starting in July 2026 instead of April 2022; 13 merged song counts also decrease.
- [x] Identify missing native song metadata: profile paths omit the leading slash
  required by the loaded-song lookup. No metadata/banner files were uploaded.
- [x] Validate the calibration compatibility fix and clearer errors with 15
  importer regression tests and the actual uploaded revision against the live
  baseline. The remaining error correctly reports 827 uploaded versus 5,918
  published logs; it does not produce a successful publication status.
- [x] Publish checkpoint a48c704; all 15 hosted importer tests pass in run
  43477814383. Live data remains byte-for-byte identical to the migration
  baseline (SHA-256 b8a95cf6889675a436b622dddaeedace6106b95040dd2e97b15c45f8a9a98bed).
- [x] Resolve the omitted legacy logs using the owner-confirmed archive repair below.

Older retained scores in the uploaded profile have no PlayerGuid. The native
local-profile exporter excludes logs whose PlayerGuid does not match, including
empty IDs. The source Save/Upload files and pending.json counters are not present
in the data branch, so whether all older logs are present locally still needs
confirmation. Do not guess ownership, replace history with totals, or bypass the
preservation checks to make this upload pass. Windows builds remain deferred.

Native lookup checkpoint a3f84b7120 is pushed to StepMania main with `[skip ci]`.
A local Linux build and isolated native capture/import verify the loaded song's
title, artist, Hard/9 chart, content-hashed PNG, preserved cumulative totals and
calibration exclusion. The same fixture confirms that empty and unrelated player
IDs are both counted as skipped for a local profile. No Windows build was run.
No publication retry was dispatched with the known-incomplete export; the user's
older source logs and pending.json counter are needed to resolve the remaining
history gap. The first actual Windows upload remains unverified for publication.

## Verified direct log migration (2026-11-14)

The owner confirmed a sole-player machine-to-named-profile migration and 5,203
skipped records, then supplied the original archive for direct repair. Only blank
PlayerGuid fields were changed in 5,203 song logs and 160 course logs. The 6,190
unique event IDs and every other byte are preserved; the original archive is
unchanged. A replacement ZIP contains all 6,309 active XML files and a hash report.
No new game preference was added and no Windows build was run.

The existing native exporter now emits 6,030 unique song events with zero skipped
records. All 827 events already on dashboard-data are byte-identical. A full local
import against the live baseline passes every preservation check, with 7,249
lifetime plays and 6,030 song events (the baseline has 7,131 and 5,918). The output
retains history back to April 2022. No real upload/publication was started; the
owner will replace the local logs and choose Upload/Retry in the current game.
