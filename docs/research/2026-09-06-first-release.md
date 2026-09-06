# Main adoption and first Open VSX release

On September 6, 2026, the maintainer-authorized research branch was merged into
`main` at `dd526c7b76dcad73f593717a93de67eaf575f55a`. The independent
**C# (with netcoredbg)** release workflow then started its first publishing run.
All eight targets passed source-build and extracted-VSIX validation. Windows x64
is publicly available and its downloaded hash matches the tested VSIX. The other
seven targets remain unpublished at the recorded check, and the GitHub release
remains a draft. Publication is not complete.

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

All eight native source-build jobs and all eight VSIX packaging jobs passed on
the first attempt. Extracted-VSIX functional validation then began on all eight
targets. The actual upload remains conditional on that complete result set.

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
permission correction was prepared and passed actionlint. The permission change remains prepared locally pending explicit maintainer
approval. The preserved version and VSIX files remain unchanged.

A later [public readback](cross-platform-2026-09-06/first-release-34031151621/public-state-before-permission.json)
confirmed Windows x64's SHA-256
`8eef6b8cfbaedd17d97f9199a059ffc9b2ba4e113260c67b1c3a99c71a6c1768`, matching the
tested release manifest. The other seven targets still returned HTTP 404.

## 5. Scheduled operation after adoption

The variant workflow is active and scheduled at `23 */6 * * *` UTC. GitHub runs
the schedule from the default branch. A published source/recipe fingerprint is
skipped by later discovery; a failed candidate remains eligible for a later run.
The first release uses the same path that subsequent automatic releases use.

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
