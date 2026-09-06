# Platform builds of netcoredbg without modifying Samsung source

On September 6, 2026, Samsung netcoredbg 3.2.0-1092 was built from source for macOS ARM64 and x64. SHA-256 checks found all 498 original input files unchanged after both builds. The self-built ARM64 debugger passed basic DAP experiments on .NET 8 and .NET 10. The x64 result covers cross-compilation and binary architecture inspection. [Build and execution evidence](netcoredbg-source-build-2026-09-06/evidence.json)

These results support trying external build scripts that produce platform packages without maintaining patches to Samsung's source. This report covers redistribution conditions, the eight targets, observed results, dependency pinning, and C# integration. Actual Windows ARM64 and Alpine build and debugging success remains unverified in this investigation.

The report defines source preservation first, then presents platform evidence and experiments, followed by a proposed build and publication design. It focuses on Samsung netcoredbg as a single engine and does not assume migration to another debugger.

The evidence and proposals have the following scope:

> Public source, GitHub runner documentation, and NuGet packages were checked on September 6, 2026. The CI design below had not been run in GitHub Actions during this investigation. Runtime execution covered standalone DAP sessions on local macOS ARM64 only. It does not establish support for all eight VSIX targets.

## 1. Redistribution terms and the source-preservation boundary

The proposed strategy checks out a fixed Samsung commit and leaves its original files unchanged. CMake options, SDK installation, dependency restoration, tests, and ZIP packaging live outside that source tree, either in this repository or a separate build repository. This permits distributing self-built binaries without accumulating downstream patches in Samsung's source. [Pinned source](https://github.com/Samsung/netcoredbg/tree/9744e1f051866215611b8440c638042aa2aa2f72)

Samsung's MIT license permits redistribution, including build outputs, provided the copyright and permission notices accompany the distribution. This supports including netcoredbg in GitHub releases and VSIX packages. [Samsung license](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/LICENSE)

Samsung's MIT notice does not cover every bundled file by itself. The default build also uses `linenoise-ng`, a JSON library, parts of CoreCLR, Roslyn DLLs, and dbgshim. `linenoise-ng` includes multiple notices in its own license file. Packaging can collect the licenses and notices for the actual included components without modifying Samsung's source. [linenoise-ng notices](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/third_party/linenoise-ng/LICENSE), [JSON license](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/third_party/json/LICENSE.MIT), [DbgShim package](https://www.nuget.org/packages/Microsoft.Diagnostics.DbgShim/10.0.731102)

C# extension integration changes are maintained separately. Source preservation here applies to Samsung's debugger inputs. Download mappings, executable selection, and arguments in the C# extension still change to connect netcoredbg. [Current executable factory](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/activate.ts#L258)

## 2. Build evidence and remaining validation for eight targets

Samsung's current source includes Windows ARM64 branches and Alpine `linux-musl` RID selection. Native libraries for all eight targets were downloaded from Microsoft's DbgShim 10.0.731102 NuGet packages, and their PE, ELF, or Mach-O CPU headers were inspected. Missing official release assets therefore do not establish that those platforms require a new port. [Platform detection](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/detectplatform.cmake), [RID selection](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/CMakeLists.txt#L351), [package URLs, hashes, and headers](netcoredbg-source-build-2026-09-06/dbgshim-platform-assets.json)

| VSIX target | .NET RID | Proposed build and test host | Evidence and status |
| --- | --- | --- | --- |
| `win32-x64` | `win-x64` | `windows-2022` | Official Samsung binary exists; self-build and execution pending |
| `win32-arm64` | `win-arm64` | `windows-11-arm` | ARM64 source branches and dbgshim exist; unmodified MSVC build and execution pending |
| `linux-x64` | `linux-x64` | `ubuntu-22.04` | Official Samsung binary exists; self-build and execution pending |
| `linux-arm64` | `linux-arm64` | `ubuntu-22.04-arm` | Official Samsung binary exists; self-build and execution pending |
| `alpine-x64` | `linux-musl-x64` | Pinned Alpine container on a Linux x64 runner | musl RID and dbgshim exist; compilation and DAP pending |
| `alpine-arm64` | `linux-musl-arm64` | Pinned Alpine container on a Linux ARM64 runner | ARM64/musl compilation and DAP pending |
| `darwin-x64` | `osx-x64` | `macos-15-intel` | Local cross-build passed; execution on Intel pending |
| `darwin-arm64` | `osx-arm64` | `macos-15` | Local source build and .NET 8/10 DAP passed; runner reproduction pending |

These runner labels exist in the GitHub documentation checked for this report. Native ARM64 runners allow the target process and debugger to run with the same architecture without assuming emulation. Explicit OS and CPU labels improve the description of the test environment but do not freeze subsequent runner-image updates. [GitHub runner list](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

Windows ARM64 can initially be tested with MSVC `-A ARM64`, `CLR_CMAKE_HOST_ARCH=arm64`, and `CLR_CMAKE_TARGET_ARCH=arm64`. Upstream Windows defaults infer x64 from a 64-bit pointer and also select x64 for automatic SDK installation. Installing an ARM64 SDK externally and passing `DOTNET_DIR` bypasses those defaults. The macOS experiments do not prove that this MSVC configuration succeeds. [Architecture defaults](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/CMakeLists.txt#L21), [SDK installation](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/fetchdeps.cmake#L41)

Alpine builds should use a musl SDK and C/C++ toolchain inside a container and execute the debugger in that environment. Explicit `CLR_CMAKE_LINUX_ID=alpine` and `RID_NAME=linux-musl` values can select the target for native and managed restoration. Renaming a glibc Linux binary does not produce a musl build. A 2025 user report describes successful musl compilation followed by non-working breakpoints, reinforcing separate build and DAP verdicts. Reproduction of that report on 3.2.0-1092 remains unverified. [musl report #201](https://github.com/Samsung/netcoredbg/issues/201)

## 3. Observed results from unmodified source builds

The experiment supplied Samsung commit `9744e1f051866215611b8440c638042aa2aa2f72` and .NET runtime `v10.0.0` commit `60629d14374c56f1cb51819049ad1fa529307f8d`. `CORECLR_DIR` provided headers and selected helper sources; the full CoreCLR runtime was not rebuilt. The toolchain used SDK 10.0.400, CMake 4.4.3, and Apple clang 21.0.0. [Build inputs and output hashes](netcoredbg-source-build-2026-09-06/evidence.json)

| Check | Result | Interpretation |
| --- | --- | --- |
| Samsung input preservation | SHA-256 matched for 498 files after both builds | Original input files unchanged; generated files and the separate runtime source tree were outside this audit |
| macOS ARM64 compilation and installation | Passed | ARM64 netcoredbg and dbgshim, ManagedPart, and four Roslyn DLLs installed |
| macOS ARM64 / .NET 8.0.24 | Eight DAP checks passed | Conditional breakpoint, stack, variables, evaluation, step, post-await breakpoint, exception, termination |
| macOS ARM64 / .NET 10.0.11 | Same DAP checks passed | Evidence for basic behavior on the .NET 10 runtime family |
| macOS x64 cross-build | Passed | Executable and dbgshim identified as x86_64; not executed |
| macOS load commands | Executables and dbgshim report `minos 12.0` for both CPUs | Metadata inspection only; no execution on macOS 12 |

The experiment reused the [earlier DAP probe and C# fixture](debugger-probe-2026-09-06/dap_probe.py), selecting self-built executables instead of official prebuilt assets. Runtime versions came from target-process output and are not claims about the latest public servicing releases. [Source integrity](netcoredbg-source-build-2026-09-06/source-integrity.json), [.NET 8 trace](netcoredbg-source-build-2026-09-06/traces/selfbuilt-net8.jsonl), [.NET 10 trace](netcoredbg-source-build-2026-09-06/traces/selfbuilt-net10.jsonl)

The ARM64 build completed installation, but its execution wrapper remained waiting on a compiler server. Terminating only the server created by that build allowed the command to return exit code 0. The later x64 build used `UseSharedCompilation=false`, `MSBUILDDISABLENODEREUSE=1`, and `DOTNET_CLI_USE_MSBUILD_SERVER=0`, completing without manual cleanup. This does not establish a universal fix for such waits. [ARM64 build log](netcoredbg-source-build-2026-09-06/logs/build-osx-arm64.log), [x64 build log](netcoredbg-source-build-2026-09-06/logs/build-osx-x64.log)

The source archive lacked Git metadata, so the self-built executable reported `3.2.0-1 (not detected, Release)` through `--version`. It did not reproduce the official build-number string. An external source SHA and build-revision manifest can identify provenance; version generation from a native Git checkout remains a later workflow check. [Upstream version generation](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/vcsinfo.cmake)

## 4. Dependencies and compatibility baselines managed outside source

Upstream defaults use CoreCLR branch `release/10.0`, SDK channel `10.0`, and the floating `*` version of `Microsoft.Diagnostics.DbgShim`. A pinned Samsung SHA alone can therefore select different dependencies over time. This experiment recorded resolved versions and hashes but did not implement fully locked restoration. [Defaults](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/CMakeLists.txt#L9), [managed dependencies](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/managed/ManagedPart.csproj), [resolved libraries](netcoredbg-source-build-2026-09-06/resolved-libraries.json)

An external build manifest can record:

- Samsung tag, commit SHA, and source archive hash
- CoreCLR input commit and archive hash
- SDK, CMake, compiler, and runner-image versions
- Linux and Alpine image digests and system package versions
- Direct and transitive NuGet versions and package hashes
- Target RID, minimum OS baseline, ZIP hash, and build recipe revision

A feed containing only approved NuGet packages, combined with external restore configuration, can constrain dependency selection without editing `ManagedPart.csproj`. Passing that configuration through the complete build and reproducing it offline remain follow-up validation work.

`DBGSHIM_DIR` requires particular care: upstream compiles its value into the executable and skips the default dbgshim installation. Supplying an absolute CI path can leave the distributed debugger looking for that same path. A portable VSIX can leave this option empty, retain executable-sibling discovery, and pin NuGet restore inputs externally. [Compile definition](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/CMakeLists.txt#L6), [library lookup](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/debugger/dbgshim.h#L50)

A target name does not define minimum OS compatibility. glibc or musl ABI, the C++ runtime, dbgshim, and the debuggee's .NET support must be considered together. Ubuntu 22.04 is an initial Linux host proposal, subject to dependency baseline checks. Alpine versions depend on the .NET versions to support. Upstream CMake sets macOS deployment target 12.0, which also appeared in the inspected binaries. [macOS compilation options](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/compileoptions.cmake#L29)

Rebuilding has limits. The default restore selected Roslyn 2.3.0 for debugger expression evaluation, independently of the extension's current Roslyn language service. Evaluating newer C# syntax in Watch therefore requires separate tests. Build automation cannot repair new .NET debugging API incompatibilities or debugger implementation defects by itself. [Expression evaluator dependencies](netcoredbg-source-build-2026-09-06/resolved-libraries.json)

## 5. Connecting debugger builds to VSIX packaging

A two-workflow design separates debugger builds from extension packaging. The debugger workflow builds and tests all eight targets when its source or dependency inputs change. A C# packaging workflow consumes a fixed manifest from a validated debugger release. Both can live in this repository; a separate repository is not a prerequisite. The later [separate-variant review](2026-09-06-samsung-debugger-variant.md) keeps the existing unmodified publication path intact. [Current workflow](https://github.com/rkttu/vscode-csharp-autobuild/blob/5cab182e77a8001f35d868c6c96a54a5cb52b45b/.github/workflows/build-and-release.yml)

Normalize each debugger package as a ZIP containing its executable, ManagedPart, Roslyn DLLs, matching dbgshim, notices, and provenance manifest. Collect each build's installed files rather than assuming managed DLLs from ARM64 and x64 builds are identical. Extracting the ZIP into a fresh directory and testing it can expose build-directory dependencies or omitted files. ZIP normalization fits the extension's existing `InstallZip` path. [Download and installation code](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/packageManager/downloadAndInstallPackages.ts#L50)

Three connections are required in the extension:

- **Debugger dependency mapping.** Select a self-built ZIP, hash, internal executable path, and executable-permission list for each target.
- **CoreCLR launch selection.** Declare a static path with `--interpreter=vscode` or choose dynamically in the factory. Follow-up inspection found a static path that uses the supplied descriptor without TypeScript changes. Other debug types do not automatically gain support.
- **Per-target installation.** Install the package through `installDebugger` after each VSIX's cleanup phase, rather than relying on a single earlier copy.

The [integration report](2026-09-06-debugger-integration.md#4-packaging-and-debugger-launch-integration-points) records source locations. Validate language services and debugging independently, and do not infer support for C# Dev Kit services, .NET Framework, Mono, mobile, or WebAssembly from a CoreCLR connection. [Registered debug types](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/activate.ts#L106)

The existing `.last_built_sha` tracks C# changes only. Comparing a combination of C# SHA, debugger manifest hash, and integration revision detects debugger-only or recipe-only updates. Those updates need a new extension version; the current `--skip-duplicate` behavior cannot deliver a different package under the same version. [Publication workflow](https://github.com/rkttu/vscode-csharp-autobuild/blob/5cab182e77a8001f35d868c6c96a54a5cb52b45b/.github/workflows/build-and-release.yml)

## 6. Experiments that determine eight-target adoption

Adoption depends on both an unmodified source build and actual debugging from the packaged output. Windows ARM64 and the two Alpine targets carry the largest remaining uncertainty. macOS x64 has a successful build but still needs execution on Intel. [Current evidence](netcoredbg-source-build-2026-09-06/evidence.json)

1. Build Windows ARM64, Alpine x64, and Alpine ARM64 in an experimental workflow with pinned Samsung and dependency inputs.
2. Extract all eight ZIPs and inspect CPU and ABI, dbgshim, companion DLLs, and notices.
3. Run launch, attach, conditional breakpoints, stepping, variables, evaluation, exceptions, and termination on native target-architecture .NET runtimes.
4. Review upstream DAP tests and generalize the original ARM64 probe. Apply the same checks to every declared .NET version.
5. Install the VSIX in VSCodium and check the language service, F5, breakpoint display, variables, and stopping. Add ASP.NET Core and remote hosts according to scope.
6. Mark only targets that pass source-preservation and behavior checks as validated. If adoption requires all eight targets together, stop publication when any target fails.

Fixing platform defects by editing Samsung's files crosses the source-preservation boundary. A strict policy can instead keep a target pending, wait for an upstream fix, or contribute a fix upstream. Keeping an older validated debugger release still requires testing its combination with new C# versions. The proposal does not label unsupported targets as supported or silently switch them to another engine.

## 7. Grounds for trying build automation first

The experiments support trying platform builds that preserve Samsung's source. Both macOS CPU builds succeeded, ARM64 debugging passed on .NET 8 and .NET 10, and matching dbgshim assets were found for all eight targets. Immediate work centers on external build settings, dependency pinning, packaged-output checks, and extension launch integration. [Direct evidence](netcoredbg-source-build-2026-09-06/evidence.json)

Long-term maintenance depends on whether new runtime and OS differences can be addressed through builds alone. Under a strict source-preservation policy, Windows ARM64 and Alpine results determine whether all eight targets can adopt the same engine together. This investigation completed research and local validation only; it did not change production workflows, VSIX packages, or external publication state.
