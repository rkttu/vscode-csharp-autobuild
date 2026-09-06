# vscode-csharp-autobuild

[![Upstream C# on Open VSX](https://img.shields.io/open-vsx/v/dotnetdev-kr-custom/csharp)](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp)
[![C# with netcoredbg on Open VSX](https://img.shields.io/open-vsx/v/dotnetdev-kr-custom/csharp-with-netcoredbg)](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg)
[![Upstream build](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/build-and-release.yml/badge.svg)](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/build-and-release.yml)
[![netcoredbg release gate](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/release-netcoredbg.yml/badge.svg)](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/release-netcoredbg.yml)

This repository builds the [upstream C# extension](https://github.com/dotnet/vscode-csharp) for Open VSX. It maintains two independent distributions: an upstream-preserving build and **C# (with netcoredbg)**, which bundles a source-built [netcoredbg](https://github.com/Samsung/netcoredbg) debugger.

The netcoredbg distribution uses native builds and functional tests on eight platform targets. Failed candidates stop before publication. Interrupted uploads resume from preserved, tested VSIX files. Microsoft and Samsung do not publish, endorse, or support these community packages.

## 1. Choosing a distribution

| Distribution | Extension ID | Debugger integration | Update policy |
| --- | --- | --- | --- |
| Upstream C# build | `dotnetdev-kr-custom.csharp` | Preserves upstream implementation and its component restrictions | Latest upstream tag by tag creation date, checked every six hours |
| C# (with netcoredbg) | `dotnetdev-kr-custom.csharp-with-netcoredbg` | Replaces the `coreclr` adapter with bundled netcoredbg | Highest numeric C# tag and eligible netcoredbg tags, released after all validation gates pass |

The upstream-preserving build changes publication metadata, the package notice, and the npm registry used for building. It does not replace the debugger or rewrite upstream extension behavior. Its workflow and `.last_built_sha` state remain independent of the netcoredbg pipeline.

The netcoredbg variant applies a small, checked overlay in a disposable C# checkout. The overlay changes extension identity, package branding, debugger acquisition, adapter selection, and SDK environment forwarding. An unexpected upstream integration change fails the build instead of silently applying an incomplete overlay. Original Samsung source files remain unchanged; this repository owns the external build and runtime compatibility code.

This differs from the community-maintained [muhammadsammy C# extension](https://github.com/muhammadsammy/free-vscode-csharp) by keeping a separate upstream-preserving distribution and automating native debugger builds, checked integration, and gated releases. It does not claim broader feature support than that project.

## 2. Installation and a first debugging session

Install **one** C# language/debug extension for a workspace. Disable other C# extension variants in that workspace to avoid competing language services and `coreclr` registrations. This package does not include C# Dev Kit.

In an editor configured to use Open VSX, search for **C# (with netcoredbg)** by **dotnetdev-kr-custom**, or open its [registry page](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg). For a manual installation, download the single VSIX matching the editor host from the [variant GitHub releases](https://github.com/rkttu/vscode-csharp-autobuild/releases). A platform VSIX is a complete extension package; installing a separate generic VSIX first is unnecessary.

| Editor host | VSIX target | Native build/test host |
| --- | --- | --- |
| Windows x64 | `win32-x64` | `windows-2022` |
| Windows ARM64 | `win32-arm64` | `windows-11-arm` |
| Linux glibc x64 | `linux-x64` | `ubuntu-22.04` |
| Linux glibc ARM64 | `linux-arm64` | `ubuntu-22.04-arm` |
| Alpine Linux x64 | `alpine-x64` | Native x64 runner with pinned Alpine container |
| Alpine Linux ARM64 | `alpine-arm64` | Native ARM64 runner with pinned Alpine container |
| macOS Intel | `darwin-x64` | `macos-15-intel` |
| macOS Apple Silicon | `darwin-arm64` | `macos-15` |

Install a native .NET SDK matching the editor host architecture and build the application in Debug configuration. For VSIX installation, use the editor's **Extensions: Install from VSIX** command. The equivalent CLI command is `code --install-extension /path/to/the-matching-package.vsix`; substitute the CLI belonging to your editor.

A minimal `.vscode/launch.json` for an application named `Example` targeting .NET 10 follows. Adjust `program` to the DLL produced by your build, then start the configuration from Run and Debug.

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Launch Example with netcoredbg",
      "type": "coreclr",
      "request": "launch",
      "program": "${workspaceFolder}/bin/Debug/net10.0/Example.dll",
      "cwd": "${workspaceFolder}",
      "console": "internalConsole",
      "stopAtEntry": false
    }
  ]
}
```

The bundled debugger needs no separate download or manual adapter path setting. The extension retains upstream SDK discovery and runtime acquisition where possible. If SDK discovery fails, inspect `dotnet --info` and the editor's C#/.NET output channels, including any configured runtime acquisition paths.

## 3. Validation coverage and limits

Every new candidate, including a C#-only update, builds and tests the debugger on all eight native targets. The pipeline then packages eight VSIX files and repeats the functional tests against each extracted debugger. A passing candidate covers 16 target/runtime combinations in each phase.

The gate includes:

- SHA-256 preservation of original Samsung source files
- Native executable and library architecture checks
- Exact dependency, debugger archive, bundled file, and VSIX hashes
- A repository fixture covering conditional breakpoints, stack frames, variables, evaluation, stepping, an async breakpoint, exception information, and normal output/exit
- The 30 automated upstream DAP scenarios listed in [`config/upstream-dap-tests.json`](config/upstream-dap-tests.json), including function breakpoints, attach, pause, disconnect, threads, exit codes, non-English names, exceptions, async stepping, generics, arrays, and indexers
- Strict rejection of missing scenarios, failed assertions, timeouts, changed binaries, or incomplete platform results
- C# compilation and adapter-factory integration checks
- VSIX identity, executable permissions, icon, provenance, and absence of a bundled `vsdbg` payload

The test runner generates external .NET 8 and .NET 10 projects that compile the original Samsung test files. It does not rewrite upstream test assertions. The manual-only `VSCodeTest297killNCD` scenario is outside the automated upstream list. New or reordered upstream scenarios stop the candidate for review.

Current build inputs are pinned in [`config/netcoredbg.json`](config/netcoredbg.json): netcoredbg baseline `3.2.0-1092`, CoreCLR headers from .NET 10.0.0, SDKs `8.0.418` and `10.0.400`, and dbgshim `10.0.731102`. Runtime tests currently use .NET 8.0.24 and .NET 10.0.11. macOS builds target a deployment minimum of 12.0, but CI execution occurs on the listed runner images; this does not prove every older OS version works.

Alpine builds include an external CoreCLR initialization wrapper using an owned 8 MiB thread stack. macOS builds include a linked `waitpid` observer for correct process exit reporting, including the non-cancelable Darwin entry point used by .NET 10. These components ship with source and license notices. [Research and troubleshooting records](docs/research/README.md) explain the underlying failures and verification evidence.

The automated matrix checks debugger protocol behavior and packaged bytes. It does not certify every editor or all language-service features. A separate installed-extension smoke test has exercised activation and .NET 8/10 launch in VS Code 1.135.0 on macOS ARM64. That result does not establish an eight-platform editor UI matrix or compatibility with every VS Code fork.

Release preparation also encountered intermittent macOS startup and exception-stack failures. The gate rejected those attempts, and the [functional-gate research note](docs/research/2026-09-06-functional-gate-and-darwin-exit.md) retains the failures and subsequent diagnostic results. Their root causes remain unconfirmed; a passing rerun does not establish that the intermittent behavior was corrected.

Only `coreclr` is advertised by the variant. Desktop .NET Framework, Unity, mobile, WebAssembly, remote debugging, Hot Reload, and full C# Dev Kit parity remain outside the release gate. Passing attach scenarios establish the tested local DAP behavior, not every IDE-specific attach workflow.

## 4. Tags, versions, and provenance

The variant detector polls both upstream tag lists. It selects the highest numeric C# version, including `-prerelease` tags, and considers netcoredbg tags from the configured baseline. A source/recipe fingerprint prevents repeat publication. A late success for an older failed debugger tag cannot automatically replace a newer published debugger. The detector processes a bounded candidate batch in ascending debugger order.

The VSIX version follows the upstream C# major and minor. Its numeric patch combines the upstream patch and this repository's packaging revision:

`VSIX patch = upstream C# patch × 1000 + packaging revision`

For example, C# `2.148.23` produces `2.148.23001` for revision 1 and `2.148.23002` for revision 2. C# `2.148.24` starts at `2.148.24001`. Revisions range from 1 through 999; exhaustion fails for maintainer review. Dry runs do not reserve a revision. Draft and completed variant releases do.

A release tag connects both sources, for example `csharp-v2.148.23-netcoredbg-v3.2.0-1092-g9744e1f05186-r1`. The full commits, original C# tag, netcoredbg tag, recipe fingerprint, validation run, and archive hashes appear in release manifests and the package's `netcoredbgBuild` metadata. An upstream prerelease tag remains a prerelease source input even though the derived VSIX uses a numeric version.

Variant releases use their own tag prefix and do not replace the repository's GitHub **Latest** release for the upstream-preserving distribution. The [versioning research note](docs/research/2026-09-06-versioning-and-merge-readiness.md) records the policy and its tradeoffs.

## 5. Scheduled operation and manual releases

The upstream-preserving workflow runs at `0 */6 * * *` UTC. The independent variant workflow runs at `23 */6 * * *` UTC, corresponding to 03:23, 09:23, 15:23, and 21:23 in Korea. GitHub schedules run from the default branch and can be delayed. Public repository schedules may be disabled after 60 days without repository activity; see [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

The variant release sequence is discovery, native build/tests, complete result aggregation, VSIX packaging, native extracted-VSIX tests, artifact preservation, Open VSX upload/readback, and GitHub release completion. All platform gates must pass before the first upload. The workflow uses one concurrency group without canceling an active release.

To run a candidate manually:

1. Open **Actions > Detect and release CSharp with netcoredbg > Run workflow**.
2. Select the branch. Leave both source tag inputs empty for automatic selection, or enter exact upstream tags.
3. Leave `publish` disabled for validation only. Enable it on `main` for publication after validation.
4. Inspect each job summary and the preserved artifacts. A successful dry run does not publish an extension.

Research-branch runs cannot publish. Scheduled `main` runs publish automatically after every gate passes. The reusable [`validate-netcoredbg.yml`](.github/workflows/validate-netcoredbg.yml) can also run standalone validation without packaging or publishing. Its Alpine-only mode is diagnostic and cannot satisfy the complete release gate.

The publisher uses the repository secret `OPENVSX_ACCESS_TOKEN` and exposes it as `OVSX_PAT` only in the final upload step. The token owner needs publication access to the existing `dotnetdev-kr-custom` namespace. A separate extension preregistration step does not run. GitHub release creation uses the workflow's `contents: write` permission.

## 6. Failures, retries, and published versions

A build or functional failure fails the Actions run, blocks that candidate, and leaves existing registry versions intact. Other eligible candidates can continue. The next scheduled run rediscovers unshipped inputs, so persistent failures can produce repeated failed runs until the maintainer resolves the cause. There is no quarantine queue or custom notification service.

Configure GitHub Actions notifications for the maintainer account. GitHub documents [workflow notification recipients](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs), including the actor associated with the schedule. Repository configuration alone does not prove that a maintainer receives email; personal notification settings and delivery are outside this pipeline.

Job summaries identify the candidate, target, last stage, failing scenarios, and publication progress where evidence exists. Native artifacts contain logs, source-integrity records, package hashes, and per-runtime results. A completed release preserves eight debugger archives, eight VSIX files, a validation manifest, a release manifest, and a compressed evidence archive. Routine Actions artifacts have limited retention; completed release assets provide longer-lived provenance.

Before uploading a platform, the publisher creates a draft GitHub release containing the tested bytes. If an upload stops after some targets succeed, a later run restores the draft assets, validates them again, skips matching registry bytes, and uploads only missing targets. If all uploads succeeded but GitHub finalization failed, the retry completes finalization without uploading again. A changed file behind an existing version or a missing preserved asset fails the retry. Publisher tests simulate these cases without altering the public registry.

Multi-platform registry publication is not atomic. A partial upload can briefly expose only some targets. The pipeline does not automatically delete published versions or downgrade users. Removing a version through [Open VSX extension management](https://github.com/EclipseFdn/open-vsx.org/wiki/Managing-Extensions) does not replace copies already installed by users. Operationally, a corrected package with a higher revision provides the normal update path; a user can also install a retained older VSIX manually. The [recovery and rollback review](docs/research/2026-09-06-publication-recovery-and-rollback.md) documents these boundaries.

## 7. Development, licenses, and support

The main implementation paths are:

- [`.github/workflows/release-netcoredbg.yml`](.github/workflows/release-netcoredbg.yml): discovery and scheduled entry point
- [`.github/workflows/netcoredbg-candidate.yml`](.github/workflows/netcoredbg-candidate.yml): complete candidate and publication pipeline
- [`scripts/validation`](scripts/validation): native builds, external compatibility code, DAP tests, and aggregation
- [`scripts/variant`](scripts/variant): source overlay, versioning, discovery, VSIX verification, and publication/resume
- [`config`](config): pinned build inputs, required platform/runtime matrix, extension identity, and required upstream tests
- [`assets/netcoredbg`](assets/netcoredbg): warm brown C# staff-line icon and design provenance
- [`docs/research`](docs/research): investigations, failure diagnoses, evidence, and operating decisions

Local gate and publication tests use synthetic evidence and fake remote services:

```sh
python3 -m unittest discover -s scripts/validation -p test_gate.py -v
python3 -m unittest discover -s scripts/variant -p 'test_*.py' -v
```

Changes to build scripts, integration code, configuration, workflow definitions, or icon assets change the recipe fingerprint and trigger a fresh candidate. Root documentation updates alone do not. Submit build/integration problems to [this repository's issues](https://github.com/rkttu/vscode-csharp-autobuild/issues), including extension version, target, SDK/runtime versions, launch configuration, and relevant logs. Avoid including credentials or private source code in reports. Upstream debugger or language-service defects can be reported upstream after identifying a reproducible component-specific case.

Repository-owned code uses the [MIT License](LICENSE). Samsung netcoredbg and upstream C# source retain their respective notices. Bundled dependencies and runtime-acquired components retain their own licenses and terms. Replacing `vsdbg` does not relicense every component of the C# extension. Package notices and upstream component documentation remain authoritative for those components.
