# Open-source debugger integration for the Open VSX C# extension

On September 6, 2026, this investigation reviewed the `vscode-csharp-autobuild` workflow and the upstream source used for the published C# 2.148.23 extension. Samsung released netcoredbg 3.2.0-1092 with a macOS ARM64 binary on June 25, 2026. That binary passed basic debugging checks against .NET 8 and .NET 10 on a local macOS ARM64 host. [Samsung release](https://github.com/Samsung/netcoredbg/releases/tag/3.2.0-1092)

This report covers the earlier adoption blocker, platform assets, observed debugging behavior, extension integration points, alternative engines, and automated publication. Integrating an open-source debugger into the C# extension is technically plausible. The current netcoredbg release provides a starting point; covering all eight existing extension targets also calls for additional builds or evaluation of an alternative such as DNCDbg.

The report first compares the earlier decision with current releases, then presents local experiments and proposed packaging changes grounded in upstream code. Its scope is the C# extension and CoreCLR debugging, not a replacement for C# Dev Kit.

A follow-up investigation evaluated building Samsung's source without modifying it. Both macOS ARM64 and x64 builds succeeded, and the self-built ARM64 debugger passed the .NET 8 and .NET 10 DAP probes. For a single-engine Samsung strategy, read the newer [source-preserving build assessment](2026-09-06-netcoredbg-source-build.md) alongside this initial comparison.

The observations have the following scope:

> Public source and release APIs were checked on September 6, 2026. This investigation ran standalone DAP sessions on macOS ARM64. It did not validate a packaged VSIX, IDE interactions, or execution on Linux or Windows. Compatibility with .NET 11 Preview and later releases remains unverified.

## 1. The official macOS ARM64 release changes the adoption baseline

[PR #3](https://github.com/rkttu/vscode-csharp-autobuild/pull/3) deferred netcoredbg adoption in November 2025 because an official macOS ARM64 binary was unavailable. Comparing that condition with the current release provides grounds to reopen the evaluation.

On May 22, 2026, a Samsung maintainer reported building and running the test suite on a Mac Studio M2. On June 25, the maintainer confirmed adding an ARM64 binary to the official release. The latest release uses commit `9744e1f051866215611b8440c638042aa2aa2f72`; the version-bump commit has a June 24, 2026 committer date. These observations do not support describing the project as completely inactive since 2024. [ARM64 test report](https://github.com/Samsung/netcoredbg/issues/174#issuecomment-4520193683), [release confirmation](https://github.com/Samsung/netcoredbg/issues/174#issuecomment-4800642087), [version commit](https://github.com/Samsung/netcoredbg/commit/9744e1f051866215611b8440c638042aa2aa2f72)

The CMake configuration for netcoredbg 3.2.0-1092 selects CoreCLR source branch `release/10.0` and SDK channel `10.0` for managed builds. This shows work toward current .NET support, but does not establish compatibility with every application or debugging feature. The README still describes macOS ARM64 as community-supported and warns about possible test failures. Binary availability and support quality are separate findings. [CMake configuration](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/CMakeLists.txt#L9), [README](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/README.md)

## 2. Release assets versus the eight existing VSIX targets

The current extension ships x64 and ARM64 VSIX packages for Windows, Linux, Alpine Linux, and macOS. The table compares release assets with those targets. An available asset does not establish successful execution on the target. [Current extension release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/v2.148.23-prerelease), [packaging targets](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/tasks/packaging/offlinePackagingTasks.ts#L45)

| VSIX target | Samsung netcoredbg 3.2.0-1092 | DNCDbg 1.2.0 | Execution in this investigation |
| --- | --- | --- | --- |
| `win32-x64` | `netcoredbg-win64.zip` | Windows x64 asset | Not tested |
| `win32-arm64` | No asset in this release | Windows ARM64 asset | Not tested |
| `linux-x64` | `netcoredbg-linux-amd64.tar.gz` | Linux x64 asset | Not tested |
| `linux-arm64` | `netcoredbg-linux-arm64.tar.gz` | Linux ARM64 asset | Not tested |
| `alpine-x64` | No musl asset in this release | Linux musl x64 asset | Not tested |
| `alpine-arm64` | No musl asset in this release | Linux musl ARM64 asset | Not tested |
| `darwin-x64` | No asset in this release | macOS x64 asset | Not tested |
| `darwin-arm64` | `netcoredbg-osx-arm64.zip` | macOS ARM64 asset | Both engines passed .NET 8 and .NET 10 checks |

Both asset lists were read from the projects' release APIs. DNCDbg 1.2.0 was released on August 28, 2026. Its stated baselines include Ubuntu 24.04 and glibc 2.39 for Linux, Alpine Linux 3.20 and musl 1.2.5 for musl, macOS 13.3, and Windows 10. Matching a VSIX target name does not establish equal support for older operating systems. [Samsung release API](https://api.github.com/repos/Samsung/netcoredbg/releases/tags/3.2.0-1092), [DNCDbg release](https://github.com/viewizard/dncdbg/releases/tag/v1.2.0)

The earlier PR's platform mappings are not directly reusable. Assigning an ARM64 binary to Linux ARM32, or a conventional Linux binary to musl, does not satisfy the target CPU and C runtime requirements. Windows ARM64's ability to execute an x64 process also does not establish debugging support for a native ARM64 .NET process. Validation must cover the mapping, target process architecture, and dynamic libraries. [Earlier PR changes](https://github.com/rkttu/vscode-csharp-autobuild/pull/3/files), [current architecture selection](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/util.ts#L119)

## 3. Observed .NET 8 and .NET 10 debugging on macOS ARM64

The local experiment downloaded official release binaries on a macOS 26.6.2 ARM64 host. ZIP SHA-256 values matched the release API digests, and `file` identified both executables as ARM64 Mach-O files. After `--help` and `--version` checks, the probe exchanged DAP messages over standard input and output. It did not use Rosetta or an x64 .NET installation. [Experiment evidence](debugger-probe-2026-09-06/evidence.json)

| Debugger | SDK and target runtime | DAP result | Program termination |
| --- | --- | --- | --- |
| netcoredbg 3.2.0-1092 | SDK 8.0.418 / .NET 8.0.24 ARM64 | All eight checks below passed | Exit code 0 |
| netcoredbg 3.2.0-1092 | SDK 10.0.400 / .NET 10.0.11 ARM64 | All eight checks passed | Exit code 0 |
| DNCDbg 1.2.0 | SDK 8.0.418 / .NET 8.0.24 ARM64 | All eight checks passed | Exit code 0 |
| DNCDbg 1.2.0 | SDK 10.0.400 / .NET 10.0.11 ARM64 | All eight checks passed | Exit code 0 |

The probe checked:

- A source breakpoint with condition `answer == 40`
- The expected source line in `stackTrace`
- `answer = 40` through `scopes` and `variables`
- `answer + 2 = 42` through `evaluate`
- Single-step execution through `next` and a `step` event
- A source breakpoint after `await Task.Delay`
- An `InvalidOperationException` stop and `exceptionInfo`
- ARM64 runtime output, standard output, and normal termination

The experiment did not cover false-condition breakpoint skipping, complex LINQ expressions, property evaluation, process attach, integrated terminals, ASP.NET Core, remote connections, or Hot Reload. Passing the basic DAP path does not establish extension-level support. .NET 9 and .NET 11 Preview were not executed.

The [DAP probe](debugger-probe-2026-09-06/dap_probe.py), [C# source](debugger-probe-2026-09-06/fixture/Program.cs), and [project](debugger-probe-2026-09-06/fixture/Probe.csproj) are included for reproduction. `evidence.json` records origins, hashes, environment details, and successful requests. The JSONL files under `traces` contain actual requests and responses with personal paths replaced.

The following commands illustrate reproduction on the same Apple Silicon architecture. They assume a .NET 10 SDK and runtime, executable permissions, and a correct `DOTNET_ROOT`. Set `--debugger` to the extracted executable.

```sh
dotnet build docs/research/debugger-probe-2026-09-06/fixture/Probe.csproj
python3 docs/research/debugger-probe-2026-09-06/dap_probe.py \
  --engine netcoredbg \
  --debugger /absolute/path/to/netcoredbg \
  --program docs/research/debugger-probe-2026-09-06/fixture/bin/Debug/net10.0/Probe.dll \
  --source docs/research/debugger-probe-2026-09-06/fixture/Program.cs \
  --log /private/tmp/netcoredbg-probe.jsonl
```

DNCDbg uses `--engine dncdbg` and its executable path. The probe supplies `--interpreter=vscode` only to netcoredbg; DNCDbg 1.2.0 starts DAP without that argument. The original experiment used `DOTNET_ROOT` and checked `ARCH=Arm64`, so its results do not constitute general cross-platform CI validation. The .NET 8 fixture was built separately with SDK 8.0.418 pinned in `global.json`.

## 4. Packaging and debugger launch integration points

Integration covers dependency download, extraction, debugger process launch, and exposed capabilities. The source review used C# 2.148.23 upstream SHA `2f5806a9f39575bfaf4ca16445f420440a43e050`. Applying these changes to another version requires checking patch compatibility and the resulting build. [Pinned upstream source](https://github.com/dotnet/vscode-csharp/tree/2f5806a9f39575bfaf4ca16445f420440a43e050)

- **Platform dependency manifest.** Entries with `id: "Debugger"` in `package.json` currently select vsdbg downloads. A separate manifest can pin each engine, source commit, URL, hash, archive format, and internal executable path. Archives contain a `netcoredbg/` or `dncdbg/` subdirectory, so `installTestPath` and the executable-permission `binaries` list must match that layout. [Dependency definitions](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/package.json#L425)
- **Archive handling.** The current installer calls `InstallZip` regardless of the URL extension. A Linux `tar.gz` URL alone does not fit that path. Options include a dedicated installer supporting both formats or repackaging verified inputs into a consistent ZIP layout. Repackaging should retain both original and resulting hashes. [Installer](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/packageManager/downloadAndInstallPackages.ts#L50), [executable permissions](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/packageManager/zipInstaller.ts#L58)
- **Debugger launch selection.** `DebugAdapterExecutableFactory` in `src/coreclrDebug/activate.ts` constructs `.debugger/<architecture>/vsdbg-ui` only when no `executable` descriptor is supplied. Declaring `program` and `args` under `contributes.debuggers` in the extension manifest allows the factory to use the descriptor supplied by VS Code. A static local integration therefore has a candidate path with no TypeScript edits. netcoredbg uses `--interpreter=vscode`; DNCDbg uses an empty argument list. Preserving dynamic SDK and target-architecture selection may require a factory change or launch wrapper. [Factory](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/activate.ts#L258), [descriptor API](https://code.visualstudio.com/api/references/vscode-api#DebugAdapterDescriptorFactory)
- **Per-platform packaging lifecycle.** `offlinePackagingTasks.ts` cleans the working directory before installing the debugger for each VSIX. Copying files into `.debugger` once near the start of the workflow can lose them during cleanup. Mapping normalized ZIPs into debugger dependencies reuses `installDebugger`, so packaging TypeScript edits are not mandatory for that approach. Custom copying or archive handling would require changes at this stage. [Packaging and cleanup](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/tasks/packaging/offlinePackagingTasks.ts#L371)
- **Configuration and capabilities.** Keeping `type: "coreclr"` can reduce `launch.json` migration effort. The same factory also registers `clr`, `monovsdbg`, `coreclr_mobile`, and `monovsdbg_wasm`; mapping all of them to a CoreCLR engine could misrepresent support. Launch settings, `pipeTransport`, launch profiles, Dev Kit brokered services, terminals, and Hot Reload require separate treatment. `pipeTransport.debuggerPath` is not a general setting for replacing the local debugger executable. [Registrations](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/activate.ts#L106), [shared configuration provider](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/shared/configurationProvider.ts)

A follow-up isolated probe transpiled and invoked the current upstream factory without modifying it. With an `executable` descriptor, the factory returned the same object and did not perform dynamic SDK discovery. This used substituted VS Code services and installation state, so it does not establish successful VSIX integration. The static path also bypasses the factory's `DOTNET_ROOT` adjustment, making correct environment and SDK discovery a separate responsibility. [Probe evidence](libre-csharp-product-2026-09-06/manifest-descriptor-probe.json)

The minimum static connection may require zero TypeScript files. A general distribution preserving SDK and architecture selection, installation checks, and capability exposure has an initial estimate of a few TypeScript files and hundreds of lines. This is not a measured patch size and excludes JSON mappings, build scripts, CI, and regression tests. Equivalent `pipeTransport`, terminal integration, source mapping, or Hot Reload would add separate feature work.

An independent debugger extension is another experiment, using a distinct debug type such as `netcoredbg`. VS Code rejects multiple descriptor factories for the same debug type, so a companion extension cannot simply register a second `coreclr` factory. Within one VSIX, static declarations or a modified factory can be selected according to the required behavior. [Registration API](https://code.visualstudio.com/api/references/vscode-api#debug.registerDebugAdapterDescriptorFactory)

The `muhammad-sammy/csharp` source changes netcoredbg's executable path and arguments. However, the inspected commit maps both macOS CPUs to the ARM64 asset, maps Linux musl to the conventional Linux asset, and omits some hashes. Its structure is a useful reference, but these mappings are not suitable for direct reuse without validation. [Community factory](https://github.com/muhammadsammy/free-vscode-csharp/blob/d94fae6e1552f1a60eacda933fc76c399b36591f/src/coreclrDebug/activate.ts#L310), [package definitions](https://github.com/muhammadsammy/free-vscode-csharp/blob/d94fae6e1552f1a60eacda933fc76c399b36591f/package.json)

## 5. Samsung netcoredbg and alternative engine options

Existing releases and test infrastructure offer starting points for comparing integration cost.

| Option | Evidence supporting evaluation | Remaining work | Initial use case |
| --- | --- | --- | --- |
| Samsung netcoredbg 3.2.0-1092 | Official macOS ARM64 asset, .NET 10 build configuration, local checks passed | Current prebuilt assets cover four of the eight targets | First experiment when retaining Samsung's engine |
| DNCDbg 1.2.0 | netcoredbg derivative, assets for all eight targets, local checks passed | Linux baselines, regressions, maintenance trajectory | Evaluate for a single engine across all eight targets |
| Self-built netcoredbg | Control over target platforms and dependencies | Own missing Windows ARM64, macOS x64, and musl builds and regression checks | Retain the same engine across all targets |
| SharpDbg | C# implementation, .NET 10 SDK basis, DAP and NuGet distribution | No execution in this investigation; native dependencies and packaging unverified | Later comparison candidate |

DNCDbg started from netcoredbg 3.1.3 and focuses on DAP. Its 1.2.0 changes include macOS ARM64 stack unwinding fixes and improvements to `DebuggerDisplay` and `DebuggerTypeProxy`. Earlier changes record source file mapping support and removal of Hot Reload. The project also removed MI/GDB, CLI, and mixed debugging. Identical behavior to netcoredbg cannot be assumed; features relevant to VS Code need individual evaluation. [DNCDbg source](https://github.com/viewizard/dncdbg/tree/7ce59f7cca0a110764c41baa6cc2312bd8c23f73), [changelog](https://github.com/viewizard/dncdbg/blob/7ce59f7cca0a110764c41baa6cc2312bd8c23f73/CHANGELOG.md), [DAP status](https://github.com/viewizard/dncdbg/blob/7ce59f7cca0a110764c41baa6cc2312bd8c23f73/docs/dap_status.md)

SharpDbg implements debugging in C# through ClrDebug and ICorDebug. At inspection, the latest `SharpDbg.Cli` NuGet version was 0.1.17. A C# implementation does not by itself remove platform-specific native dependencies. [SharpDbg repository](https://github.com/MattParkerDev/sharpdbg), [NuGet package](https://www.nuget.org/packages/SharpDbg.Cli/0.1.17)

netcoredbg and DNCDbg use MIT licenses permitting modification and redistribution with copyright and license notices. A VSIX also needs notices for accompanying files such as dbgshim and managed debugger DLLs. This finding covers the debugger licenses; it is not a license audit of every dependency in the existing extension. [netcoredbg license](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/LICENSE), [DNCDbg license](https://github.com/viewizard/dncdbg/blob/7ce59f7cca0a110764c41baa6cc2312bd8c23f73/LICENSE)

## 6. Adoption sequence and publication gates

Debugger updates should be tracked independently from C# upstream updates. The current workflow compares `.last_built_sha` with the upstream SHA. A debugger-only change would not trigger that comparison, and republishing the same extension version may be skipped by `--skip-duplicate`. Recording the upstream SHA, debugger manifest hash, and integration patch revision together, with a new extension version for downstream changes, addresses that gap. [Current workflow](https://github.com/rkttu/vscode-csharp-autobuild/blob/5cab182e77a8001f35d868c6c96a54a5cb52b45b/.github/workflows/build-and-release.yml), [Open VSX publication](https://github.com/eclipse-openvsx/openvsx/wiki/Publishing-Extensions)

An initial non-publishing experiment could integrate netcoredbg 3.2.0-1092 for `darwin-arm64` and `linux-x64`, retaining the Roslyn language service and changing the `coreclr` launch path. Optionally connecting DNCDbg 1.2.0 through the same adapter boundary would permit comparison without extensive duplicated integration code. This is a proposal, not an implemented extension configuration.

Platform expansion depends on the intended release scope. Four platforms can start with Samsung's official assets. Simultaneous coverage of all eight requires validating DNCDbg or owning builds for Samsung's missing targets. Automatically switching engines by operating system could change features and errors; a single default engine is the proposed baseline.

Before publication, inspect the final VSIX for remaining vsdbg executables and download paths, then validate language-service startup and debugger startup separately. Passing DAP tests is insufficient to report IDE integration without checking F5, breakpoint display, variables, stopping, and exception settings in VSCodium. Other editors such as Cursor and remote extension hosts require their own compatibility checks. [Debugger extension guide](https://code.visualstudio.com/api/extension-guides/debugger-extension)

The proposed implementation checks are:

1. Record pinned engine versions, hashes, and platform executable paths.
2. Connect the `coreclr` launch declaration and debugger dependencies; extend the factory where dynamic behavior is required. Fail the build on incompatible upstream patches.
3. Inspect archive layout, executable permissions, companion libraries, and notices in the final VSIX.
4. Validate launch, attach, breakpoints, stepping, variables, exceptions, and termination on .NET 8 and .NET 10 for each OS and CPU.
5. Test ASP.NET Core profiles and environment variables, source mapping, terminals, Remote SSH, and containers within the declared scope.
6. Install the VSIX in VSCodium and verify Roslyn and the debugging UI together.
7. Verify debugger-only version updates and publication stops on failed checks.

## 7. Resolved blocker and remaining product validation

The current official netcoredbg release provides evidence for revisiting macOS ARM64 and .NET 10 support, reinforced by local DAP tests. Initial implementation can focus on downloads, launch paths, archives, and platform mapping. A large debugger modernization fork is not a prerequisite for starting integration experiments. [Official release](https://github.com/Samsung/netcoredbg/releases/tag/3.2.0-1092), [local evidence](debugger-probe-2026-09-06/evidence.json)

Longer-term costs depend on runtime regression testing and ownership of missing platform builds. Samsung's current release is a starting point for retaining its engine and expanding targets. For an eight-target comparison, DNCDbg remains an option subject to Linux baseline and IDE validation; the follow-up source-build report evaluates the Samsung-only route. This initial investigation added research and standalone evidence only. It did not change the production workflow, integrate a VSIX, commit changes, or publish externally.
