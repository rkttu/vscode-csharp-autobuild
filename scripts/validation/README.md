# Native netcoredbg source-build and DAP validation

The reusable [all-platform workflow](../../.github/workflows/validate-netcoredbg.yml)
now covers Windows, Ubuntu, Alpine and macOS on x64 and ARM64. It reads pinned
dependencies from [netcoredbg.json](../../config/netcoredbg.json), runs the same
.NET 8/10 DAP fixture and requires complete, hash-matched evidence in
`aggregate.py`. `validate-unix.py` implements the Unix recipe; the Windows
implementation remains in `validate-windows.ps1`.

The final candidate passed all eight source builds and all sixteen .NET 8/10
runtime combinations with unchanged Samsung inputs. Alpine required external
compilation inputs, exact RID dependency selection and a hosting correction:
CoreCLR initialization runs on an owned 8 MiB pthread stack. Samsung files
remain unchanged, but the repository now maintains runtime hosting behavior
as well. All eight VSIX packages also passed the same runtime checks using
their extracted debugger files.
The [cross-platform report](../../docs/research/2026-09-06-cross-platform-release.md)
records the complete matrix, crash evidence and source-preservation boundary.
The independent [variant workflow](../variant/README.md) cannot package or publish
a candidate until the full native gate passes.

`diagnose-netcoredbg-alpine.yml` reuses the pinned failing-run artifacts and
collects debugger exit codes and stacks on disposable runners. Its successful
job status describes collection only; its DAP result files remain authoritative.
The diagnostic workflow never promotes artifacts or publishes an extension.

Manual `validate-netcoredbg.yml` dispatch accepts `platform-scope=alpine` for
isolated experiments. This mode skips the aggregate and cannot promote a
debugger. Normal release candidates use the default `all` scope.

## Windows-specific recipe and historical experiment

This experiment builds Samsung netcoredbg on native Windows x64 and ARM64 runners and runs the same basic DAP fixture on .NET 8 and .NET 10. It supports the investigation in [issue #2](https://github.com/rkttu/vscode-csharp-autobuild/issues/2). It does not build VSIX packages, create releases, publish to Open VSX, or update `.last_built_sha`.

The original [Windows workflow](../../.github/workflows/validate-netcoredbg-windows.yml) is retained for manual Windows-only diagnosis. Its initial branch-scoped push trigger enabled the first research run and has since been removed in favor of the reusable all-platform workflow. GitHub exposes `workflow_dispatch` after default-branch registration. [GitHub dispatch requirements](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)

## Pinned inputs and native execution

| Input | Selection |
| --- | --- |
| Samsung tag | `3.2.0-1092` |
| Samsung source | `9744e1f051866215611b8440c638042aa2aa2f72` |
| CoreCLR source | `60629d14374c56f1cb51819049ad1fa529307f8d` (`v10.0.0`) |
| Build and test SDKs | `10.0.400` and `8.0.418` |
| dbgshim | `10.0.731102` |
| x64 runner | `windows-2022` |
| ARM64 runner | `windows-11-arm` |

The workflow installs isolated SDKs with an explicit architecture and verifies the OS, `dotnet.exe`, `netcoredbg.exe`, `dbgshim.dll`, and debuggee architecture. It uses MSVC's Visual Studio 2022 generator with explicit target and CoreCLR architecture options. Native Windows ARM64 runner availability is documented by [GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

`ManagedDependencies.targets` overrides the floating dbgshim version through the external `DirectoryBuildTargetsPath` MSBuild input. No Samsung project file is edited. Original tracked files are hashed before the build and checked again even if a later build or runtime test fails. Generated files are outside that integrity comparison.

This experiment pins source commits, SDK versions, action commits, and dbgshim. It records other restored package versions and hashes from `project.assets.json`. It does not yet provide a fully locked offline NuGet restore or a frozen runner/compiler image. These limits are separate from preserving Samsung's original files.

The first Windows run exposed an MSVC/NuGet build-directory collision: the native `corguids.vcxproj` read the managed project's `obj/project.assets.json` and failed with `Sequence contains no elements`. The recipe therefore builds native targets with `BUILD_MANAGED=OFF`, publishes the unchanged `ManagedPart.csproj` into a separate directory, and collects the same managed DLLs and dbgshim that upstream installs. This adjustment belongs to the external build recipe.

## Checks and recorded results

`validate-windows.ps1` performs the following work:

1. Verify source SHAs and native OS/SDK architecture; record SDK, CMake, and Visual Studio details.
2. Configure, compile, and install netcoredbg without changing Samsung input files.
3. Check required installed files, collect notices, and inspect native PE architecture and hashes.
4. Copy the installed debugger to a fresh directory and run its version command there.
5. Build the fixture with each selected SDK, run it directly, and debug it over DAP.
6. Record source integrity, package hashes, per-runtime results, and an overall verdict.

The DAP checks require a conditional breakpoint, stack and variables, expression evaluation, step-over, a breakpoint after `await`, exception information, expected runtime and CPU output, and clean termination. Absence of a supported exception filter fails the probe instead of silently reducing coverage. Both runtimes are attempted even if one fails, and the architecture matrix uses `fail-fast: false`.

Artifacts named `netcoredbg-validation-windows-<arch>-<attempt>` retain `evidence/` and the experimental `package/` for 14 days. `evidence/result.json` identifies the last stage and overall result; `dap-net8-result.json` and `dap-net10-result.json` record individual runtime checks. Build and DAP logs, source hashes, restored libraries, and PE inspection results accompany them. Setup failures before the script starts may have only the GitHub job log.

The original [macOS probe and evidence](../../docs/research/debugger-probe-2026-09-06/) remain unchanged. The validation probe derives from that experiment and adds explicit expected runtime and architecture, result files, and bounded cleanup. The new probe passed eight checks each on local macOS ARM64 with .NET 8 and .NET 10; a deliberately wrong x64 expectation failed. Local helper checks also rejected modified or deleted source files and mismatched CPU headers in actual Windows dbgshim libraries. These checks validate the test tools, not Windows execution.

## Scope of a successful run

A green result establishes the recorded Samsung source build and basic standalone launch debugging on the selected Windows runner and runtimes. It does not establish process attach, VSIX installation, IDE interactions, remote sessions, integrated terminals, all vsdbg features, or other OS targets. Experimental artifacts are not production debugger releases.

The workflow uses read-only repository permissions and checkout without persisted credentials. All build outputs and SDK installations use temporary runner directories. Production publication remains in the existing, unchanged workflow.
