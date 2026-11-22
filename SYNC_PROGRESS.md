# Manual upload progress

- [x] Define the allowlisted version 1 XML/metadata/banner export.
- [x] Reuse the dashboard builder with injected song/banner metadata.
- [x] Preserve event GUIDs and deduplicate retries without dropping distinct same-time plays.
- [x] Reject missing historical totals, song counts, and daily/monthly play history.
- [x] Add trusted-code Actions dispatch, serial Pages publishing and an unchanged-site bootstrap.
- [x] Pass nine importer tests and workflow YAML parsing locally.
- [x] Verify the engine-generated export against this importer.
- [x] Publish workflows, run hosted checks, and bootstrap the current live site.
- [x] Confirm successful publication in run 43550339204, data revision 7879e2d02bdab5b0873bbd5cb08b4f7ef283ef78. The owner later clarified that the separate log-repair ZIP had not been installed.

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
- [x] Prepare and locally verify the owner-confirmed legacy-log repair below; installation was not confirmed.

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

## Missing-banner audit and backfill (2026-11-14)

Upload run 43550339204 succeeded, preserving 6,030 song events; it does not confirm installation of the separate log-repair ZIP. Its export
contains no song metadata/banner envelopes, so the live site uses the retained
1,353 images. Audited the supplied Windows game folder: 1,110 songs lack images,
including 29 recent rows (25 distinct songs). Corrected the manual builder's
native cache discovery to Cache/Banner, with compatibility for staged
Cache/Banners and explicit overrides. All 20 importer/cache tests pass.

Prepared a local outbox patch with 354 recovered images from exact song matches,
including 313 from Songs 2 and two video stills; nine backgrounds and four jackets
replace unavailable dedicated banners. All recent rows have images after import.
The remaining 756 records lack exact folders or usable artwork in this copy.
The existing native exporter retains the patch, and a full local import passes
all published-history checks. All 6,030 original event files, score lists, totals,
and existing images are unchanged. The patch and detailed reports remain outside
Git; no live data was uploaded or published. StepMania checkpoint a8e1474992 fixes
the native cache lookup with a passing cached-image regression test. Windows
builds remain deferred.


## Temporary Pages download failure (2026-11-20)

Run `44749866449` accepted data revision `79e288e44c21776e5beeba4c8d02bd7cf8deffe5`, then failed while fetching a retained banner from the live Pages baseline with HTTP 503. The builder/history-validation and deployment steps never ran. The previous site remains online at revision `94b9eb657ce0d140481ea5ba31ef105be85eaa02`, with 7,266 lifetime plays and 6,047 recorded song events. Its data.json SHA-256 is `a73222d12172d1b5549c6fe5d8c527f54d340a0d7f64c63f7dcf7d07dceb64c0`.

Plan: retry temporary HTTP/network errors with a bounded delay and clear asset diagnostics, keep permanent/oversized failures and all history checks strict, add focused fault-injection tests, and validate the exact accepted export against the live baseline. Commit/publish the reviewed server-side fix, then rebuild the existing accepted upload and verify the live revision and preserved history. No Windows build or local Save changes. Evidence stays outside Git under `/tmp/stepmania-dashboard-run-44749866449/`.

Implemented five-attempt baseline downloads with bounded exponential delay, capped Retry-After support and diagnostics identifying the failing URL. Permanent HTTP errors and size limits remain strict; exhausted banner downloads still fail the baseline step. All 30 tests pass, including ten new download tests covering 503 recovery, temporary/permanent status handling, network and response-read interruptions, retry limits, Retry-After seconds/dates, size limits and failure without a partial banner. Full accepted-upload validation completed below.

The exact accepted revision passes the importer and all history checks against the current live data.json: 7,281 lifetime plays and 6,062 recorded song events, each 15 higher than the published site. Git confirms all 15 new events are dated November 20 and no older event, song metadata or banner changed. All 2,467 song-to-banner references remain unchanged. Local verification fetched 312 historical images directly, matched them byte-for-byte to the retained cache, and reused the remaining 1,041 cached images; all 1,353 retained output images match. The production workflow still fetches its required images from Pages. The tested server-side change was then published and the accepted upload rebuilt successfully, as verified below.

Fix `f2e959f` is published on main. All 30 hosted tests pass in run `44752917681`, and replacement publication [44752978898](https://github.com/chihduo/stepmania-dashboard/actions/runs/44752978898) succeeded using the same accepted data revision. The live dashboard now reports 7,281 lifetime plays and 6,062 recorded song events, including all 15 new November 20 events. Every live data field matches the locally validated output except its generation timestamp; three sampled live banner files also match byte-for-byte. Live data.json SHA-256: `cbe4d519cc07cc27d59402f6e5385c4423121ff26191bd5a4dd96d15402d3cf6`. No Windows build was run and no local profile or play-log files were changed.

## Song detail counts and selected difficulty (2026-11-22)

Plan: audit DISCOTHEQUE against the accepted export, earlier site and original
Save archive; make the selected chart and lifetime-versus-detail counts explicit;
check the recent-play/tab flow in a browser; publish and verify unchanged data.

Accepted revision `84b081092fec6be5d3c69bd5ddecbbce16b0450e` has 10 lifetime Hard
plays for `Songs/DDR POP/DISCOTHEQUE/` and six detailed Hard records (one clear,
five failures). The recent entry selects Medium, which has two plays and two
records. The same four-record Hard gap exists in the October 6 site and the
original supplied Save archive; it was not introduced by automatic uploading.
The window now labels lifetime and detailed counts separately, highlights the
selected difficulty, explains missing details, and labels judgments as based on
available records. Source counts and event data remain unchanged.

All 30 existing importer tests pass. A real-browser check reproduces two Medium
rows and six Hard rows before and after the change, verifies the selected-tab
state and gap message, and checks the empty-detail case and the modal at 1280 px
and 390 px widths. A full rebuild passes history validation and produces identical
data fields except the generation timestamp: 7,290 lifetime plays and 6,071 logged
plays. All 1,705 referenced banner files are byte-identical. Evidence and browser
captures are in `/tmp/stepmania-dashboard-song-history-20261122/`. No game
executable or local Save changes were needed.

Fix `aff55d3` is published on main. Hosted tests passed in run `44987541394`;
publication [44987563035](https://github.com/chihduo/stepmania-dashboard/actions/runs/44987563035)
succeeded using the same accepted upload. The live HTML matches the reviewed
page byte-for-byte, and all data fields except generation time remain identical
to the previous site (7,290 lifetime plays and 6,071 logged plays). Live data.json
SHA-256: `927b75b2c1f8211b8216c95600d2d9886ac283c2ab8fd1c52bdf9b72a3c825e8`.

## Counter rollback and retained score history (2026-11-22)

Runs `45024038241` and `45024379465` both reject accepted revision
`67c1aa995bfacc6b12f85e892d6c296009d895f9` at the per-song history check.
`Songs/DDR POP/Gokuraku Jodo/` falls from 17 to 15 plays (Medium 16 to 14).
The newer supplied archive independently contains 16 in the earlier outbox and
machine profile but 14 in the saved local profile. All previous event files are
byte-identical; 28 new events bring the upload from 6,071 to 6,099 logs and
7,290 to 7,318 lifetime plays. This is distinct from the November 20 HTTP 503.
The same rebuild would also drop three previously published profile-only high
scores after the local retained lists changed (Lupin Medium and Holiday Hard).

Plan: preserve known published chart counters and score records across normal
profile reloads/list trimming; check profile identity, cumulative totals, daily
log history and known event IDs before merging; keep missing songs/charts and
ambiguous chart recovery strict. Add regression tests for retry idempotence,
legacy/GUID score matching, rollback, pruning and real missing events. Validate
the complete accepted revision, commit, publish and verify all old scores and
28 new events. No Windows build or user Save changes. Evidence stays under
`/tmp/stepmania-dashboard-failure-45024379465/`.

Implemented recovery from the published baseline for uniquely identified chart
counters and score records. Profile-wide and dated-log checks remain strict;
known published event IDs are additionally checked against the actual uploaded
event files before recovery. Missing songs/charts and ambiguous custom-chart
recovery still fail. Recomputed pack/artist totals use the preserved song counts.
Workflow logs and sync status identify recovered counters and records.

All 44 tests pass, including 14 new regression cases. The full accepted revision
now builds with 7,318 lifetime plays and 6,099 upload events. It preserves all
6,422 previously published chart records and adds exactly 28, for 6,450 chart
records. Gokuraku Jodo remains at 17 plays; the three pruned profile-only scores
are retained. Every existing banner is byte-identical. A second full rebuild
produces identical data except its generation timestamp. Only songs and their
pack/artist aggregates differ from the rejected candidate; all activity series,
recent plays, profile totals and raw upload files are unchanged. Ready to publish.
