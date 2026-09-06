# Upstream version mapping and merge readiness

The subsequent [publication recovery and rollback review](2026-09-06-publication-recovery-and-rollback.md) expands the operational assessment below. It identifies missing quarantine and deliberate recovery-release controls; the successful build and branch-compatibility findings remain unchanged.

On September 6, 2026, the research branch adopted an upstream-based version policy and replaced the initial icon. The new candidate is `2.148.23001`, derived from C# `v2.148.23-prerelease` and netcoredbg `3.2.0-1092`. The preceding `0.1.4000` candidate was a dry run and was never published to Open VSX. [Candidate discovery](../../scripts/variant/discover.py), [new validation run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34023125844)

This report records the accepted numeric mapping, release provenance, revision allocation, icon, verification evidence and merge assessment. It separates source-control readiness from the first registry publication.

The sections first explain version ordering and retries, then describe the asset change and the evidence supporting integration into `main`.

## 1. Numeric versions tied to upstream C# releases

The package keeps the upstream major and minor components. Its numeric patch is `upstream_patch * 1000 + packaging_revision`. Revisions range from 1 through 999 for each upstream numeric version. The generator rejects exhaustion instead of silently carrying into the next upstream patch. [Version implementation](../../scripts/variant/versioning.py), [boundary tests](../../scripts/variant/test_versioning.py)

| Upstream C# version | Packaging revision | VSIX version | Meaning |
| --- | --- | --- | --- |
| 2.148.23 | 1 | 2.148.23001 | First adopted combination |
| 2.148.23 | 2 | 2.148.23002 | New debugger or packaging recipe with the same C# base |
| 2.148.23 | 999 | 2.148.23999 | Last revision before explicit policy review |
| 2.148.24 | 1 | 2.148.24001 | New C# patch, ordered above every preceding patch-23 revision |

The upstream `-prerelease` suffix remains in the source tag recorded in provenance; the numeric package version omits it. It does not imply that the upstream source became a stable release. If upstream publishes different source under stable and prerelease tags with the same numeric version, each newly adopted source combination can receive another packaging revision.

Microsoft's Marketplace publishing guide specifies three numeric components and does not fully support SemVer prerelease suffixes. This is a publishing-service constraint, not proof that the `vsce` packager rejects every SemVer suffix: the installed packager accepted both prerelease identifiers and build metadata in a direct validator check. Build metadata alone does not establish a newer SemVer version, so a debugger-only update cannot rely on `+netcoredbg...` to advance ordering. The accepted numeric policy avoids that ambiguity without claiming it is the only possible Open VSX policy. [Marketplace publishing guide](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#pre-release-extensions), [manifest contract](https://code.visualstudio.com/api/references/extension-manifest), [SemVer precedence](https://semver.org/#spec-item-10)

## 2. Release tags and full source provenance

The first candidate uses GitHub release tag `csharp-v2.148.23-netcoredbg-v3.2.0-1092-g9744e1f05186-r1`. The abbreviated debugger commit makes the tag readable; complete hashes remain in the release metadata, release manifest and package's `netcoredbgBuild` object. [Tag construction](../../scripts/variant/versioning.py), [package overlay](../../scripts/variant/overlay.py)

The package records the C# source tag and full commit, upstream numeric version, original source manifest version, netcoredbg tag and full commit, packaging revision, release tag and policy identifier. It also retains the validated debugger archive hash, workflow commit and validation run ID. The original manifest version is kept separately because the source snapshot's placeholder is not a reliable substitute for the selected C# tag.

The verifier reconstructs the numeric mapping from package provenance and checks it against the VSIX version. The final gate also compares the recorded source and version identities with the discovered candidate. This connects the installed version to the two exact source revisions and the tested bytes. [VSIX verifier](../../scripts/variant/verify-vsix.py), [publication gate](../../scripts/variant/publish.py)

## 3. Revision reservations and interrupted uploads

Draft and completed variant releases reserve their recorded revision. A dry run creates neither and therefore does not consume a revision. A debugger-only update, source retag or recipe change can create a new candidate fingerprint and revision. Documentation under `docs/research` is outside the recipe fingerprint, so adding evidence does not cause another package build. [Discovery implementation](../../scripts/variant/discover.py)

Candidates run serially. Discovery chooses a bounded window of newer debugger tags and orders new candidates from older to newer, giving the newest successful engine the highest numeric revision. Automatic discovery excludes debugger tags below the latest published engine. This prevents a previously failing older tag from later receiving a higher package version and downgrading the engine. An explicit manual tag selection remains an intentional override. [Discovery regression tests](../../scripts/variant/test_discovery.py), [workflow ordering](../../.github/workflows/release-netcoredbg.yml)

An interrupted publication resumes from the draft's original VSIX files, version and release tag. It compares existing Open VSX bytes before completing remaining targets. It does not rebuild an already reserved version. If GitHub asset upload itself was interrupted, recovery can stop on a missing asset until the original file is restored. Deleting draft metadata or manually publishing outside this allocator can break its reservation history; retaining release records keeps version assignment consistent. Actual registry recovery remains unexecuted. [Recovery helper](../../scripts/variant/resume.py), [failure and recovery record](2026-09-06-build-troubleshooting.md)

## 4. Warm brown lettering on a musical staff

The replacement [icon](../../assets/netcoredbg/icon.png) places large deep-brown C# lettering over five lighter-brown staff lines on an opaque pale cream background. It uses a simpler composition than the initial debugger symbol. The built-in image generator produced the image and refined its background. [Design prompt and asset notes](../../assets/netcoredbg/README.md)

The committed PNG is 1254 by 1254 pixels, 8-bit RGB with no alpha channel. The overlay copies the same file into all eight packages, and VSIX verification compares its bytes with the repository asset. Samsung/netcoredbg attribution remains in descriptive text and component notices. The artwork has no Samsung wordmark, oval or Tizen emblem. [Overlay asset handling](../../scripts/variant/overlay.py), [VSIX icon check](../../scripts/variant/verify-vsix.py)

## 5. Verification of the revised candidate

The changed version and discovery code passed eighteen unit tests. The evidence gate passed nine tests covering acceptance and release-blocking failures. `actionlint` accepted the netcoredbg workflows. A local overlay of the real upstream C# snapshot passed the actual modified activation/factory test and `npm run compile`, including TypeScript, ESLint and upstream generation tasks. These isolated checks are separate from native and installed-editor execution. [Version tests](../../scripts/variant/test_versioning.py), [discovery tests](../../scripts/variant/test_discovery.py), [gate tests](../../scripts/validation/test_gate.py)

Run `34023125844` completed successfully with the revised recipe at `4b0b41ea198014a6384ff513e4ab660a8125bb8a`. All eight native source-build targets, sixteen source-build runtime combinations, eight VSIX builds, sixteen extracted-adapter runtime combinations and the final publication dry run passed. Every target preserved all 498 original Samsung files. The actual registry upload step was skipped. [Actions run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34023125844), [archived summary](cross-platform-2026-09-06/candidate-34023125844/summary.json), [job and step conclusions](cross-platform-2026-09-06/candidate-34023125844/jobs.json)

The real macOS ARM64 VSIX from this run was installed into temporary VS Code directories. VS Code 1.135.0 activated extension version `2.148.23001` and passed both .NET 8 and .NET 10 launch sessions, including conditional breakpoints, stack/variables, evaluation, stepping, a post-await breakpoint, native runtime output and clean exit. The editor process exited with code 0. The VSIX SHA-256 is `8d38fa0fe6d2f3789c569944179e434b30a1812942e9c69b7b94ee93437d9596`, matching the runner's package record. Its packaged icon bytes also match the committed asset. [Installed-editor result](cross-platform-2026-09-06/candidate-34023125844/editor-smoke/ide-result.json), [reproduction and scope](cross-platform-2026-09-06/candidate-34023125844/README.md)

The historical `0.1.4000` run already passed eight VSIX builds and sixteen extracted-adapter combinations, followed by two actual VS Code extension-host launch sessions on macOS ARM64. Those historical results do not by themselves verify the new version or icon. [Earlier candidate and editor evidence](2026-09-06-cross-platform-release.md)

## 6. Merge scope and first-publication boundary

The refreshed `origin/main` is `5cab182e77a8001f35d868c6c96a54a5cb52b45b` and is an ancestor of the research branch. The existing production workflow, `.last_built_sha` and root README have no changes relative to that commit. The new extension uses its own name, release tags and workflow concurrency group. Its GitHub releases use `--latest=false`, preserving the existing release marker. [Existing main commit](https://github.com/rkttu/vscode-csharp-autobuild/commit/5cab182e77a8001f35d868c6c96a54a5cb52b45b), [separate workflow](../../.github/workflows/release-netcoredbg.yml)

The source-control check found no merge conflict against that main revision, and the revised candidate passed the complete validation path. No blocking implementation or merge issue was identified within this tested scope. The branch is technically ready for a merge that intentionally adopts the scheduled publication behavior described below. The branch has not been merged. No Open VSX publication has occurred.

Merging this workflow into the default branch activates its six-hour schedule. Scheduled `main` runs request publication automatically after every gate passes; a manual `main` run defaults to a dry run unless publication is selected. The first live upload will verify the configured token, namespace access, registry acceptance and downloaded hashes. Those operational checks and interrupted-upload recovery remain outside the completed dry runs. [Publication condition](../../.github/workflows/release-netcoredbg.yml), [publisher readback](../../scripts/variant/publish.py)

The supported evidence covers source preservation and local launch scenarios on Windows, Linux, macOS and Alpine, each on x64 and ARM64, with .NET 8 and .NET 10. It does not establish complete replacement of every Microsoft debugger feature. Attach, remote sessions, integrated terminals, Hot Reload, full language-service acceptance and VSCodium remain separate validation work. The all-target gate stays in place for future tags. [Scope and troubleshooting record](2026-09-06-build-troubleshooting.md)
