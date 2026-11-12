# Manual upload progress

- [x] Define the allowlisted version 1 XML/metadata/banner export.
- [x] Reuse the dashboard builder with injected song/banner metadata.
- [x] Preserve event GUIDs and deduplicate retries without dropping distinct same-time plays.
- [x] Reject missing historical totals, song counts, and daily/monthly play history.
- [x] Add trusted-code Actions dispatch, serial Pages publishing and an unchanged-site bootstrap.
- [x] Pass nine importer tests and workflow YAML parsing locally.
- [ ] Verify the engine-generated export against this importer.
- [ ] Publish workflows, run hosted checks, and bootstrap the current live site.
- [ ] Verify the first upload of the user's actual Windows profile (requires its local history and credential).

The current live site remains on legacy gh-pages publication during implementation.
No real user statistics or banners have been uploaded by this development session.
