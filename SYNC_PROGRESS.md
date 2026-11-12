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
