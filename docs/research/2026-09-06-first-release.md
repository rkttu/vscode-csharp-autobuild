# Main adoption and first Open VSX release

On September 6, 2026, the maintainer-authorized research branch was merged into
`main` at `dd526c7b76dcad73f593717a93de67eaf575f55a`. The independent
**C# (with netcoredbg)** release workflow then started its first publishing run.
All eight targets passed source-build and extracted-VSIX validation.
[Recovery run 34034255861](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34034255861)
then completed publication of version `2.148.23001` on all eight Open VSX targets.
The workflow and a separate full-download check verified every public VSIX hash.
The [paired GitHub release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v2.148.23-netcoredbg-v3.2.0-1092-g9744e1f05186-r1)
became public at 12:57:19 UTC with all 19 preserved assets.

## 1. Scope adopted into main

The branch adds an independent eight-platform netcoredbg distribution, native
functional gates, source and binary provenance, tag discovery, numeric version
mapping, VSIX integration, publication and interrupted-upload recovery. The root
[README](../../README.md) now covers both distributions, installation, validation
limits, scheduled operation, failure handling, development, and component notices.

The existing `dotnetdev-kr-custom.csharp` workflow and `.last_built_sha` are
byte-identical to pre-merge main commit
`5cab182e77a8001f35d868c6c96a54a5cb52b45b`. The new extension retains its separate
identity `dotnetdev-kr-custom.csharp-with-netcoredbg` and warm brown musical-staff
icon.

## 2. Candidate evidence before adoption

[Dry run 34028072085](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34028072085)
finished successfully after diagnostic reruns. The accepted set covers eight
targets, .NET 8/10, and both source-build and extracted-VSIX phases. Each of those
32 combinations passed eight repository fixture checks and 30 upstream DAP
scenarios. All 498 original Samsung files remained unchanged per native target.

[The final candidate archive](cross-platform-2026-09-06/candidate-34028072085-final/README.md)
preserves the manifests, complete-set summary, workflow result, and hashes of the
input evidence. A separate installed-extension check passed activation and seven
checks per runtime in VS Code 1.135.0 on macOS ARM64. Repository gate, discovery,
versioning and publication fault tests passed 37 local test cases.

The macOS Intel startup failure and macOS ARM64 exception-stack failure remain
in the [functional-gate research record](2026-09-06-functional-gate-and-darwin-exit.md).
Diagnostic reruns passed without changing the tests or candidate. Their root
causes remain unconfirmed; the successful results do not establish a fix for
intermittent behavior.

## 3. First main-branch publication run

[Run 34031151621](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34031151621)
started on the merge commit with publication enabled and explicit source tags:

- C# `v2.148.23-prerelease`, commit `2f5806a9f39575bfaf4ca16445f420440a43e050`
- netcoredbg `3.2.0-1092`, commit `9744e1f051866215611b8440c638042aa2aa2f72`
- VSIX `2.148.23001`, packaging revision 1
- Recipe `ee1443d0d2bc0a76dfbd129e574126d6badfeaa9a55bf7aed861750df4f085f5`
- Paired tag `csharp-v2.148.23-netcoredbg-v3.2.0-1092-g9744e1f05186-r1`

All eight native source-build jobs, eight VSIX packaging jobs, and eight
extracted-VSIX functional gates passed on their first attempt. Both runtime
phases passed all required fixture checks and the 30 upstream DAP scenarios.

The first-release macOS ARM64 VSIX also passed a separate installed-extension
check in VS Code 1.135.0. Activation and seven checks per runtime passed on
.NET 8.0.24 and .NET 10.0.11, and all installed debugger bytes matched the package.
Its SHA-256 is `5051f72839d07e518ef60fba6c64add0794a73e242ec92de7eeae97beefb780c`.
[First-release editor evidence](cross-platform-2026-09-06/first-release-34031151621/editor/README.md)
records this result separately from registry publication.

## 4. Live publication failures and recovery corrections

All native, packaging and extracted-VSIX jobs in run 34031151621 passed on their
first attempt. The final upload step acknowledged Windows x64 at 12:21:28 UTC,
but immediate public metadata readback returned HTTP 404. The publisher failed
without finalizing the GitHub release. It had already preserved all 19 release
assets: eight debugger archives, eight VSIX files, two manifests and the evidence
archive. Its status correctly reported no hash-verified registry targets.

At 12:25:38 UTC, public Windows x64 metadata returned HTTP 200. Open VSX
[v1.1.2's publication handler](https://github.com/eclipse-openvsx/openvsx/blob/v1.1.2/server/src/main/java/org/eclipse/openvsx/publish/PublishExtensionVersionHandler.java)
performs asynchronous storage/scanning and keeps versions inactive until the
process completes. The pinned CLI's success output acknowledges submission; it
does not prove immediate public visibility. The observed delay was approximately
four minutes, not a rejected namespace registration or a failed debugger test.

Commit `f00801b079f94c3fceb37d91f915a55c880f5025` changes the publisher to submit
each missing target once, then wait against one 15-minute visibility deadline.
Only HTTP 404 is treated as pending. All public downloads must match the tested
hashes, and timeout still fails the run. Discovery now completes preserved drafts
before introducing new source/recipe candidates. The updated local suite passes
43 tests, including asynchronous visibility, timeout without reupload, and draft
selection after a publisher recipe change.

[Recovery attempt 34033328801](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34033328801)
exposed a separate integration gap: its read-only discovery token could not see
the draft release. It selected a new candidate instead and was canceled before
publication. GitHub's [release-list API documentation](https://docs.github.com/en/rest/releases/releases#list-releases)
limits draft listings to callers with push access. A job-scoped `contents: write`
permission correction passed actionlint. After explicit maintainer approval,
commit `dd115e3` granted that permission to discovery. Native build and packaging
jobs retain read access. The preserved version and VSIX files remain unchanged.

[Recovery run 34034255861](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34034255861)
used empty tag inputs and selected the original revision-1 fingerprint
`46d3aacd73532b6365d62b82f6d4a9e9a40d126236aa9987e2eb8b076fd59346`.
It skipped native builds, packaging and extracted-VSIX tests and restored the
complete tested set from the draft before entering the publisher.

An older [scheduled run 34033536801](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34033536801)
started on `f00801b` before the permission correction and was canceled to avoid
continuing the incorrect new-candidate path. Before cancellation, its macOS
ARM64 source gate failed `VSCodeTestUnhandledException` on .NET 10 (29/30 passed,
exit 1, no timeout); .NET 8 passed 30/30. This is another recorded intermittent
exception-test failure, not evidence that a rerun corrected its cause. No
artifacts from this failed candidate replace the preserved first-release set.

A pre-correction [public readback](cross-platform-2026-09-06/first-release-34031151621/public-state-before-permission.json)
confirmed Windows x64's SHA-256
`8eef6b8cfbaedd17d97f9199a059ffc9b2ba4e113260c67b1c3a99c71a6c1768`, matching the
tested release manifest. The other seven targets returned HTTP 404 in that
historical snapshot.

The successful recovery submitted the seven missing targets between 12:50:39
and 12:51:04 UTC. It completed all public hash comparisons and release
finalization at 12:57:19 UTC, without rebuilding or uploading Windows x64 again.
[The recovery archive](cross-platform-2026-09-06/first-release-34031151621/recovery-34034255861/README.md)
contains the exact resumed candidate, unchanged release manifest, final
publication status, public release readback, and independent download hashes
for every target. The GitHub tag still points to the validated merge commit.

## 5. Scheduled operation after adoption

The variant workflow is active and scheduled at `23 */6 * * *` UTC. GitHub runs
the schedule from the default branch. A published source/recipe fingerprint is
skipped by later discovery; a failed candidate remains eligible for a later run.
The first release uses the same path that subsequent automatic releases use.
GitHub-hosted runners execute the entire path without a local terminal or
assistant session. The workflow was confirmed active after recovery.

Read-only discovery after completion selected `2.148.23002` for the changed
recipe rather than reusing the published `2.148.23001` reservation. No second
release was built or published by that check. The next scheduled run will
reconsider current upstream tags and the recipe, run every gate for a fresh
candidate, and publish only a complete passing set. Documentation changes
alone do not change the recipe.

All target gates precede the first upload. The publisher preserves tested files
in a draft release, reads back each public VSIX hash, and finalizes the GitHub
release only after all targets match. Fault tests exercise partial-upload and
finalization recovery using fake remote services. No intentional production
upload failure is injected into the first public release.

## 6. Remaining verification boundaries

The runtime matrix does not establish every editor UI, remote-debugging path,
Hot Reload behavior, .NET Framework scenario, or C# Dev Kit feature. The local
editor check covers VS Code on one macOS ARM64 machine. Actual maintainer email
delivery depends on personal GitHub notification settings and is not proven by
repository configuration. Intermittent macOS failures remain documented for
future investigation, and any future failing candidate still stops at the gate.
