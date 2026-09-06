# netcoredbg build failures, fixes and recovery evidence

On September 6, 2026, the research branch progressed from native Windows checks to an eight-platform C# VSIX candidate. Candidate `0.1.4000` passed all native builds, .NET 8/10 source-build probes, extracted-VSIX probes and the final publication dry run. A local VS Code extension host also activated its macOS ARM64 package and debugged both runtimes. Earlier failures remain useful regression fixtures. [Successful candidate](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34021654129), [archived results](cross-platform-2026-09-06/summary.json)

This record explains the source-preservation boundary, failure signatures, dependency selection, evidence gates, packaging integration and recovery procedure. It records what actually failed separately from static review findings and unexecuted publication paths.

The sequence below starts at compiler and runtime failures, then follows the tested bytes into the extension. The final sections cover diagnosing future failures and recovering interrupted runs.

## 1. Fixed inputs and the source-preservation boundary

The successful baseline used Samsung tag `3.2.0-1092` at `9744e1f051866215611b8440c638042aa2aa2f72`, CoreCLR source input `60629d14374c56f1cb51819049ad1fa529307f8d`, DbgShim `10.0.731102`, and SDKs `8.0.418` and `10.0.400`. The fixture processes reported runtimes `8.0.24` and `10.0.11`. Alpine ran in a digest-pinned `alpine:3.22.1` container on native x64 and ARM64 hosts. Windows and macOS used native GitHub runners. [Configuration](../../config/netcoredbg.json), [workflow](../../.github/workflows/validate-netcoredbg.yml)

The audit hashes tracked Samsung input files before building and checks them again in the script's finalization path, including after failures. All 498 original files remained unchanged in the successful candidate. This audit does not cover generated files, the separate CoreCLR input tree, or repository-owned compatibility code. It proves preservation of Samsung's original files; it does not mean that the resulting Alpine executable contains only upstream code. [Audit implementation](../../scripts/validation/audit.py), [final native evidence](cross-platform-2026-09-06/candidate-34021654129/native/)

Source commits, SDKs, DbgShim and action revisions are pinned. Runner images, compiler packages and some transitive restores can still change. Recorded package hashes and resolved library versions establish provenance for a run, not bit-for-bit reproducibility across future infrastructure updates.

## 2. Compiler failures and exact dependency selection

The following failures occurred during actual runs. Their corrections belong to the external build recipe.

| Signature | Root cause | Applied correction | Evidence |
| --- | --- | --- | --- |
| MSVC `corguids.vcxproj`: `Sequence contains no elements` | Managed restore placed `project.assets.json` in a location also examined by the native project | Build native targets with `BUILD_MANAGED=OFF`; publish unchanged `ManagedPart.csproj` into separate intermediate/output directories | [First Windows failure](windows-validation-2026-09-06/first-run/run.json), [passing Windows run](windows-validation-2026-09-06/passing-run/run.json) |
| Alpine C++ conversion from `NULL`/`nullptr` to a metadata token | musl's C++ definition of `NULL` differs from assumptions in upstream integer casts | Force-include an external header that loads relevant system declarations, then defines `NULL` as Clang's GNU null constant | [Initial Alpine failure](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34018624437), [compatibility header](../../scripts/validation/musl-null-compat.h) |
| Alpine `strerror_r`: integer return value used as a pointer | `_GNU_SOURCE` selects the upstream GNU branch, but musl supplies the POSIX integer-return function | Select the existing POSIX branch for `src/utils/err_utils.cpp` only | [Signature failure](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34018846705), [CMake include](../../scripts/validation/musl-compat.cmake) |
| `strerror_r` no longer declared after the previous change | Removing `_GNU_SOURCE` alone did not request the POSIX declaration | Apply both `-U_GNU_SOURCE` and `-D_POSIX_C_SOURCE=200809L` to that compilation unit | [Intermediate failure](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34019169442) |
| Alpine ARM64 requires `ld-linux-aarch64.so.1` | The managed publish selected a glibc native shim despite the requested musl RID | Copy the native file from the exact pinned `Microsoft.Diagnostics.DbgShim.linux-musl-arm64` package and record both NuGet and native hashes | [Dependency failure](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34019652479), [selection code](../../scripts/validation/validate-unix.py) |

An RID passed to `dotnet publish` did not prove the identity of the native asset collected from that output directory. The final recipe selects the exact NuGet package/RID path and independently inspects the executable and shim headers. ELF, Mach-O and PE checks reject a CPU mismatch. The source and package hashes then connect these files to the DAP result. [Native header checks](../../scripts/validation/audit.py), [aggregate gate](../../scripts/validation/aggregate.py)

The managed dependency override uses `DirectoryBuildTargetsPath` and an external targets file to pin DbgShim without editing Samsung's project. Native and managed builds remain separate on all platforms. Restored component licenses and the runtime third-party notices accompany the package. [Managed dependency inputs](../../scripts/validation/ManagedDependencies.targets), [Windows recipe](../../scripts/validation/validate-windows.ps1)

## 3. Alpine's apparent timeout and the actual CoreCLR crash

After compilation and RID selection were corrected, both Alpine CPUs still failed both runtime probes. The visible symptom was a DAP timeout. The adapter had actually exited with `-11` (`SIGSEGV`), while inherited pipe handles kept the reader from observing an immediate EOF. The probe now records the adapter exit code at failure and cleans up the process group it created on POSIX. A timeout can therefore be distinguished from a live adapter that is genuinely stuck. [Failing complete matrix](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34019887224), [probe](../../scripts/validation/dap_probe.py)

The diagnostic workflow reused those exact binaries, enabled core capture only on disposable runners and collected backtraces before deleting its own core files. The stacks followed `ManagedCallback::CreateProcessW` to `Interop::Init` and `coreclr_initialize`. The installed runtime was stripped, so the innermost CoreCLR symbol was not established by these dumps. The call chain was consistent with the musl hosting issue described in dotnet/runtime #103741. That issue explains a stack probe consuming the full stack reserved for a DBI callback thread. [archived stacks](cross-platform-2026-09-06/alpine-crash/), [runtime issue](https://github.com/dotnet/runtime/issues/103741)

The accepted workaround links repository-owned `musl-coreclr-host.cpp` into Alpine builds. A linker wrapper intercepts only this executable's lookup of `coreclr_initialize`; other `dlsym` requests pass through. Initialization executes on an owned pthread with an 8 MiB stack. The caller joins the thread before returning the original status and output arguments. The code does not change process-wide CLR environment variables. Its source and the repository MIT notice are included in the debugger notices. [Hosting compatibility source](../../scripts/validation/musl-coreclr-host.cpp)

The isolated [Alpine experiment](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34021312326) passed all four CPU/runtime combinations. The later complete candidate passed all sixteen combinations, then repeated them successfully using the packaged adapters. This validates the recorded initialization and launch scenario. Future runtime stack behavior, unusual host configuration and broader debugger scenarios still require execution evidence. The `8 MiB` choice is an owned-stack workaround for the tested runtime behavior, not a universal CoreCLR guarantee.

## 4. C# integration and packaging observations

The first isolated factory test showed that a manifest executable descriptor can reach the upstream factory. Actual product integration also required changing hard-coded extension IDs, retaining SDK/`DOTNET_ROOT` handling, selecting one VSIX target, replacing offline debugger installation and assigning the independent version after NBGV rewrites `package.json`. The overlay uses checked text anchors and stops if those upstream integration points move. [Overlay](../../scripts/variant/overlay.py), [factory and activation test](../../scripts/variant/test-factory.cjs)

A static contract review found an additional activation problem before the real editor test: removing debugger types from the manifest while retaining their descriptor-factory registrations violates VS Code's registration rule. The overlay now removes both the unsupported declarations and those registrations, keeping `coreclr`. The isolated test invokes the actual modified activation function and compares registrations with the package manifest. This finding did not come from a failed production editor session. [VS Code registration implementation](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/api/common/extHostDebugService.ts)

Upstream formatting and compile checks run after the overlay. The real package test compares the extension identity, target, version, icon bytes, executable permission bits and every debugger payload hash. Packaging does not rebuild the debugger. Unix packages are assembled on Linux so executable modes survive the VSIX archive. [VSIX verifier](../../scripts/variant/verify-vsix.py), [candidate workflow](../../.github/workflows/netcoredbg-candidate.yml)

The local editor test installed the real macOS ARM64 VSIX into temporary user-data and extension directories. The executable name came from the app's `CFBundleExecutable` (`Code`), and the inherited `ELECTRON_RUN_AS_NODE` variable was removed from that child environment. Otherwise the app binary interpreted editor arguments as Node options. VS Code 1.135.0 then activated the extension and completed both launch scenarios. [Editor procedure and traces](cross-platform-2026-09-06/editor-smoke/README.md)

## 5. Reading results without promoting incomplete evidence

The source-build result, job conclusion and release eligibility answer different questions. An Alpine-only experiment intentionally skips aggregation. The diagnostic workflow can succeed while every DAP result fails, because its job is to collect evidence. A release candidate requires all eight successful native jobs and a matching aggregate manifest, then all eight package jobs, all eight extracted-adapter jobs and the final complete-set check. [Workflow boundaries](../../.github/workflows/validate-netcoredbg.yml), [gate implementation](../../scripts/validation/aggregate.py)

When a run fails, inspect the following evidence in order:

1. Read the first failed workflow step and `evidence/result.json` to locate environment, configuration, native build, managed build or runtime testing.
2. Compare the recorded source commits, SDKs, runtime output, DbgShim selection, runner image and architecture with the last successful run.
3. Read the corresponding build log or `dap-net*-result.json`; for a timeout, inspect `adapterExitCodeAtFailure` before assuming a live hang.
4. Verify `source-integrity.json`, `debugger-architectures.json` and `package-sha256.json` before reusing binaries.
5. Read `validation-manifest.json` for missing targets, identity mismatch or hash disagreement. A set of individually green jobs can still fail this gate.
6. For packaging failures, inspect the overlay anchor, NBGV version rewrite, public restore and VSIX result. For extracted-adapter failures, compare the embedded bytes with the native package before investigating runtime behavior.

After workflow cleanup, manual validation uses the release entry point with publication disabled. The full eight-platform gate replaces the former Alpine-only dispatch:

```sh
gh workflow run release-netcoredbg.yml --ref main -f publish=false
```

The baseline diagnostic workflow was retired after the first release. Its pinned failing-run artifacts and the two diagnostic Actions records were removed during maintainer-authorized cleanup; its source and archived stacks remain available. To repeat that investigation, restore the historical recipe on a disposable branch and select available failing binaries. Archived text is not a runnable binary. Normal native artifacts use fourteen-day retention; validated archives and candidate VSIX artifacts use thirty days. Adopted publication assets are preserved in a separate GitHub release. [Historical diagnostic workflow](https://github.com/rkttu/vscode-csharp-autobuild/blob/62117f140ed351739889b4f783fe59f42e74c13d/.github/workflows/diagnose-netcoredbg-alpine.yml), [archived stacks](cross-platform-2026-09-06/alpine-crash/), [validation artifact settings](../../.github/workflows/validate-netcoredbg.yml)

## 6. Retries, release identity and remaining operating boundaries

Whole-run retries retain their original workflow/source identity. The aggregate selects the latest available attempt for a target while accepting an earlier successful target from the same run. It rejects evidence from another run or workflow revision. Changes to SDKs, source commits, build inputs, integration code or packaged assets produce a different candidate fingerprint and trigger fresh validation. [Aggregate attempt selection](../../scripts/validation/aggregate.py), [discovery](../../scripts/variant/discover.py)

Open VSX publication is not atomic across eight targets. The publisher first preserves the tested files and manifests in a draft release. On retry it compares existing registry bytes and restores the original version and assets; it does not silently overwrite an existing platform version. A draft with incomplete GitHub asset uploads still needs its missing original assets recovered. Real registry publication and interrupted-upload recovery have not yet been exercised. [Publisher](../../scripts/variant/publish.py), [recovery helper](../../scripts/variant/resume.py)

The initial `0.1.4000` candidate and charcoal icon are historical. The subsequent accepted version policy follows C# major/minor and encodes `upstream_patch * 1000 + revision`, while a descriptive Git tag and manifest record connect both source versions. The icon now uses warm brown C# lettering on an opaque cream musical staff. Version comparison, revision exhaustion, and stale-tag downgrade prevention have dedicated tests. [Current version policy and merge assessment](2026-09-06-versioning-and-merge-readiness.md)

The existing unmodified C# distribution remains independent. Passing this pipeline establishes the recorded local launch checks across its eight platform targets. Attach, remote sessions, integrated terminals, Hot Reload, full language-service acceptance, VSCodium and other runtime versions remain separate validation work. A future build failure can be investigated from this record without weakening the all-target release gate.
