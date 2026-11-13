# Manual upload progress

- [x] Define the allowlisted version 1 XML/metadata/banner export.
- [x] Reuse the dashboard builder with injected song/banner metadata.
- [x] Preserve event GUIDs and deduplicate retries without dropping distinct same-time plays.
- [x] Reject missing historical totals, song counts, and daily/monthly play history.
- [x] Add trusted-code Actions dispatch, serial Pages publishing and an unchanged-site bootstrap.
- [x] Pass nine importer tests and workflow YAML parsing locally.
- [x] Verify the engine-generated export against this importer.
- [x] Publish workflows, run hosted checks, and bootstrap the current live site.
- [ ] Verify the first upload of the user's actual Windows profile (requires its local history and credential).

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
- [ ] Publish the fix and verify hosted importer checks.
- [ ] Resolve the omitted legacy logs before publishing the user's new data.

Older retained scores in the uploaded profile have no PlayerGuid. The native
local-profile exporter excludes logs whose PlayerGuid does not match, including
empty IDs. The source Save/Upload files and pending.json counters are not present
in the data branch, so whether all older logs are present locally still needs
confirmation. Do not guess ownership, replace history with totals, or bypass the
preservation checks to make this upload pass. Windows builds remain deferred.
