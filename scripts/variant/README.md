# Independent C# with netcoredbg release automation

The extension ID is `dotnetdev-kr-custom.csharp-with-netcoredbg`, with display name
`C# (with netcoredbg)`. The [root README](../../README.md) covers installation,
support scope, schedules, versions, and maintainer operations. The original C#
distribution and its production workflow remain independent.

## Entry points and gates

- `release-netcoredbg.yml`: tag discovery, publication-boundary tests, and serial candidate selection
- `netcoredbg-candidate.yml`: native source validation, eight VSIX packages, native extracted-adapter validation, and publication
- `validate-netcoredbg.yml`: eight native targets, .NET 8/10 smoke and upstream DAP suites, source preservation, and aggregation

Each native phase requires the repository fixture and all 30 scenarios in
`config/upstream-dap-tests.json`. The external test projects reference original
Samsung C# files. Missing, failed, timed-out, or mismatched evidence blocks release.
Alpine uses repository-owned CoreCLR hosting compatibility; macOS uses a linked
Darwin process-exit observer. Neither implementation edits Samsung source files.

`overlay.py` works in a disposable C# checkout, verifies the debugger archive,
and applies checked integration replacements. The build compiles actual upstream
TypeScript. `test-factory.cjs` checks registration, adapter selection, and SDK
forwarding. `verify-vsix.py` validates package identity, permissions, icon, payload
hashes, provenance, and the extracted adapter. Only `coreclr` is advertised.

## Versioning and discovery

`versioning.py` maps C# `major.minor.patch` to
`major.minor.(patch * 1000 + revision)`. Revisions range from 1 through 999.
For example, C# 2.148.23 revisions 1 and 2 produce `2.148.23001` and
`2.148.23002`; C# 2.148.24 starts at `2.148.24001`.

GitHub tags contain the upstream C# version, debugger tag and abbreviated SHA,
and packaging revision. Package metadata and release manifests retain complete
commits. Draft and completed releases reserve versions; dry runs do not.
`versioning.validate` rejects inconsistent identities at every boundary.

`discover.py` examines upstream tags directly, including tags without GitHub
releases. It compares source and recipe fingerprints against completed releases,
restores interrupted drafts, and selects a bounded batch of eligible tags.
Automatic selection excludes debugger tags older than the latest published
engine. Within a batch, ascending debugger order gives newer engines higher
package revisions. A failed candidate does not suppress subsequent candidates.
C#-only changes currently rebuild and retest the full matrix.

## Publication and retry

Only scheduled `main` runs or explicitly selected manual `main` runs publish.
Other branches can run complete dry runs. Only the final upload step receives
`OPENVSX_ACCESS_TOKEN` as `OVSX_PAT`.

`publish.py` requires complete native VSIX evidence before preserving a draft
GitHub release and uploading any target. Every public registry download must
match the tested VSIX hash. GitHub finalization occurs after all eight readbacks.
The variant release does not replace the original distribution's Latest release.

`resume.py` restores the draft release's VSIX files and evidence. Existing matching
registry bytes are skipped. Different bytes behind an existing version stop the
release. Missing preserved files also stop the retry. There is no automated
rollback or quarantine service; maintainers respond to failed Actions runs.
`publication-status.json` and job summaries expose the last stage and verified
targets without changing the publication policy.

`test_publication.py` exercises partial-upload recovery, finalization-only retries,
matching-byte skips, hash mismatch rejection, missing assets, and incomplete
functional evidence using temporary files and fake remote services. These tests
do not deliberately interrupt a real public registry upload.

## Evidence and limitations

[Research records](../../docs/research/README.md) preserve historical candidate
runs, actual editor-host checks, build failures, versioning decisions, and the
publication/recovery review. The earlier `0.1.4000` candidate was never published;
its evidence is historical. A later `2.148.23001` candidate passed the smaller
smoke gate before the upstream suite was added. Current recipe validation is
recorded separately and must not be inferred from either earlier success.

The native DAP matrix does not certify every IDE, language-service feature,
remote workflow, Hot Reload implementation, or C# Dev Kit feature. Installed-editor
launch testing has separate evidence for VS Code on macOS ARM64.
