# Manual upload progress

- [x] Define the allowlisted version 1 XML/metadata/banner export.
- [x] Reuse the dashboard builder with injected song/banner metadata.
- [x] Preserve event GUIDs and deduplicate retries without dropping distinct same-time plays.
- [x] Reject missing historical totals, song counts, and daily/monthly play history.
- [x] Add trusted-code Actions dispatch, serial Pages publishing and an unchanged-site bootstrap.
- [x] Pass nine importer tests and workflow YAML parsing locally.
- [x] Verify the engine-generated export against this importer.
- [ ] Publish workflows, run hosted checks, and bootstrap the current live site.
- [ ] Verify the first upload of the user's actual Windows profile (requires its local history and credential).

Hosted importer tests pass (run 43249599943), and the native C++ export passes through the Python importer. The live data matches the retained gh-pages snapshot byte-for-byte (SHA-256 b8a95cf6889675a436b622dddaeedace6106b95040dd2e97b15c45f8a9a98bed; 7,131 lifetime plays). The Pages environment currently allows gh-pages only, so main must be added before migration.
No real user statistics or banners have been uploaded by this development session.
