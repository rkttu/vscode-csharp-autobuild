# First-release validation and partial publication

Main run 34031151621 passed eight native builds and eight extracted-VSIX gates on .NET 8/10, including the 30 upstream DAP scenarios per combination. The public Windows x64 VSIX matches the tested SHA-256 `8eef6b8cfbaedd17d97f9199a059ffc9b2ba4e113260c67b1c3a99c71a6c1768`. The other seven target endpoints still returned HTTP 404 at the recorded check. The GitHub release remains a draft containing all 19 preserved assets.

Publication failed because the first upload was accepted before its public metadata became available. The publisher now has a bounded asynchronous-visibility wait. The first recovery attempt could not list draft releases with its read-only discovery token and was canceled before publication. The job-scoped permission correction is prepared pending maintainer approval.

The [first-release report](../../2026-09-06-first-release.md) explains the results and remaining publication boundary. Editor tests, native/VSIX summaries, exact release manifests, the original publication error, and the public readback are kept separately. No VSIX or debugger binary is committed here.
