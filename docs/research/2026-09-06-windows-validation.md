# Windows x64 and ARM64 source-build and debugging results

On September 6, 2026, a validation-only GitHub Actions workflow built Samsung netcoredbg from unchanged source and passed basic DAP checks on native Windows x64 and ARM64 runners with .NET 8 and .NET 10. Both jobs checked all 498 original Samsung input files and found no changes. [archived run metadata](windows-validation-2026-09-06/passing-run/run.json)

The work also translated the four preceding research reports into English, reopened [issue #2](https://github.com/rkttu/vscode-csharp-autobuild/issues/2), and continued on `research/netcoredbg-windows-validation`. The existing production workflow, extension ID, build state, and Open VSX publication path remain unchanged.

The results below cover the pinned inputs, an initial build failure and its external recipe fix, four runtime checks, and remaining integration work.

> These results establish standalone debugger source builds and DAP launch behavior on the recorded Windows runners. No VSIX or IDE integration, process attach, remote debugging, full vsdbg feature parity, or eight-platform release was validated. The x64 runner uses Windows Server 2022; the ARM64 runner uses Windows 11. This is not a test of every supported Windows desktop version.

## 1. Pinned source and native target selection

The workflow checks out Samsung tag `3.2.0-1092` at commit `9744e1f051866215611b8440c638042aa2aa2f72` and uses .NET runtime `v10.0.0` commit `60629d14374c56f1cb51819049ad1fa529307f8d` for CoreCLR headers and helper sources. The full CoreCLR runtime is not rebuilt. SDKs `8.0.418` and `10.0.400` and dbgshim `10.0.731102` are selected explicitly. [Workflow source](https://github.com/rkttu/vscode-csharp-autobuild/blob/62117f140ed351739889b4f783fe59f42e74c13d/.github/workflows/validate-netcoredbg-windows.yml), [build script](../../scripts/validation/validate-windows.ps1)

| Target | Runner | Native compiler path | Observed source integrity |
| --- | --- | --- | --- |
| Windows x64 | `windows-2022`, image `20260830.290.1` | MSVC `Hostx64/x64/cl.exe` | 498 original files unchanged |
| Windows ARM64 | `windows-11-arm`, image `20260830.155.1` | MSVC `Hostarm64/arm64/cl.exe` | 498 original files unchanged |

Both builds used MSVC 19.44.35228.0 and Windows SDK 10.0.26100.0. The script verifies the OS architecture, SDK executable PE header, debugger and dbgshim PE headers, and target-process architecture reported through DAP. The ARM64 result therefore covers a native ARM64 compiler, debugger, and debuggee. [x64 configuration](windows-validation-2026-09-06/passing-run/x64/configure.log), [ARM64 configuration](windows-validation-2026-09-06/passing-run/arm64/configure.log)

The shallow checkouts produce the version string `3.2.0-1 (9744e1f, Release)`, rather than the official release build number. The recorded tag and complete commit SHA identify the source independently of that generated string. [x64 version output](windows-validation-2026-09-06/passing-run/x64/debugger-version.log), [ARM64 version output](windows-validation-2026-09-06/passing-run/arm64/debugger-version.log)

## 2. An external build recipe change for MSVC and NuGet

The [first run](windows-validation-2026-09-06/first-run/run.json) configured both native compilers and built ManagedPart, then failed in the native `corguids.vcxproj` NuGet resolution step with `Sequence contains no elements`. The logs point to the shared native and managed output directory: the managed `obj/project.assets.json` was available beside the native project. Neither job reached DAP tests, and both still passed source-integrity checks. [First-run evidence](windows-validation-2026-09-06/first-run/run.json)

The corrected recipe builds the native `netcoredbg` target with `BUILD_MANAGED=OFF`, then publishes the original `ManagedPart.csproj` into separate intermediate and output directories. It collects the same managed DLLs and dbgshim that upstream's installation rules select. The separate `ManagedDependencies.targets` file pins dbgshim through MSBuild's external `DirectoryBuildTargetsPath`; Samsung source files remain untouched. [Recipe fix](https://github.com/rkttu/vscode-csharp-autobuild/commit/4b769fd23afcbf867d538ca0c9ace0ed824f6494), [external dependency input](../../scripts/validation/ManagedDependencies.targets)

Both jobs passed using this recipe. This resolves the observed build collision for the selected inputs; it does not establish that every future tag or compiler version will build without adjustments.

## 3. Four passing runtime and architecture combinations

Each job built the fixture with the selected SDK, executed it directly, and debugged it with a fresh copy of the installed debugger. Every DAP session passed all eight checks. [x64 result](windows-validation-2026-09-06/passing-run/x64/result.json), [ARM64 result](windows-validation-2026-09-06/passing-run/arm64/result.json)

| Debugger architecture | SDK | Runtime observed in debuggee output | DAP checks | Termination |
| --- | --- | --- | --- | --- |
| x64 | 8.0.418 | .NET 8.0.24, `ARCH=X64` | 8 passed | Exit code 0 |
| x64 | 10.0.400 | .NET 10.0.11, `ARCH=X64` | 8 passed | Exit code 0 |
| ARM64 | 8.0.418 | .NET 8.0.24, `ARCH=Arm64` | 8 passed | Exit code 0 |
| ARM64 | 10.0.400 | .NET 10.0.11, `ARCH=Arm64` | 8 passed | Exit code 0 |

The checks cover a source breakpoint with `answer == 40`, stack location, scopes and variables, `answer + 2 = 42` evaluation, step-over, a breakpoint after `await`, an exception breakpoint with `exceptionInfo`, and expected output with normal termination. The runtime numbers are observations from these pinned installations, not claims about the latest public servicing releases. [DAP probe](../../scripts/validation/dap_probe.py), [x64 .NET 8](windows-validation-2026-09-06/passing-run/x64/dap-net8-result.json), [x64 .NET 10](windows-validation-2026-09-06/passing-run/x64/dap-net10-result.json), [ARM64 .NET 8](windows-validation-2026-09-06/passing-run/arm64/dap-net8-result.json), [ARM64 .NET 10](windows-validation-2026-09-06/passing-run/arm64/dap-net10-result.json)

The downloaded artifact binaries were also hashed locally and matched the hashes of the relocated executables inspected on the runners. Both `netcoredbg.exe` and `dbgshim.dll` had the expected PE architecture. [x64 binary evidence](windows-validation-2026-09-06/passing-run/x64/debugger-architectures.json), [ARM64 binary evidence](windows-validation-2026-09-06/passing-run/arm64/debugger-architectures.json)

## 4. Verification-only execution and retained evidence

The workflow has read-only repository permissions, uses checkout without persisted credentials, and writes build outputs and SDKs to temporary runner directories. It has no schedule or release trigger, no VSIX packaging, and no Open VSX publication step. The research-branch push filter permits verification without adding the workflow to `main`; `workflow_dispatch` is also declared for use after default-branch registration. [Workflow operation](../../scripts/validation/README.md)

The passing workflow revision is `4b769fd23afcbf867d538ca0c9ace0ed824f6494`. Its two artifacts contain the experimental binaries and detailed evidence, with 14-day retention. Text evidence is committed separately so the findings remain reviewable after artifact expiration. The archive normalizes UTF-8 BOMs, CRLF, ANSI formatting, and trailing horizontal whitespace in logs and records original and archived file hashes. [Artifact metadata](windows-validation-2026-09-06/passing-run/artifacts.json), [archive provenance](windows-validation-2026-09-06/passing-run/archive-provenance.json)

The workflow and PowerShell script passed local syntax checks. Before Windows execution, the generalized DAP probe passed .NET 8 and .NET 10 on macOS ARM64 and rejected a deliberately wrong x64 expectation. The audit tool accepted real Windows x64 and ARM64 dbgshim files and rejected opposite CPU expectations and modified or missing source inputs. These checks supplement the Windows runs rather than replace them.

## 5. Implications for the separate Samsung variant

Windows ARM64 is now supported by direct evidence for the selected source-preserving build and basic debugging scope. Combined with the earlier macOS experiments, this strengthens the proposed Samsung-only build strategy. It does not establish eight-platform coverage: Linux and Alpine source-build validation, macOS x64 execution, and actual extension integration remain outstanding. [Earlier source-build assessment](2026-09-06-netcoredbg-source-build.md), [separate-variant design](2026-09-06-samsung-debugger-variant.md)

The next integration experiment can consume these Windows build outputs while preserving the existing unmodified C# distribution. It still needs to validate packaging, extension identity and version handling, SDK selection, launch and attach, and actual IDE behavior before claiming a working `C# (with Samsung Debugger)` VSIX.

## 6. Completed Windows verification and remaining release work

Both Windows architectures passed unchanged Samsung source builds and all four .NET/runtime DAP combinations after one external build-layout correction. The workflow source and evidence remain in Git history and the research archive. After release adoption, the maintainer requested removal of the temporary workflow, its two Actions runs, and the research branch. Issue #2 stays open for follow-up coverage. [Passing run](windows-validation-2026-09-06/passing-run/run.json)

The immediate Windows build uncertainty is reduced for the pinned inputs. Longer-term operation still depends on repeating checks across new upstream tags, dependency and compiler changes, and the remaining targets. No production release or Open VSX publication was performed as part of this verification.
