# File-based app debugging without additional upstream changes

Research date: November 3, 2026. Scope: [issue #11](https://github.com/rkttu/vscode-csharp-autobuild/issues/11), specifically `dotnetdev-kr-custom.csharp-with-netcoredbg`. Repository inspected at `e649fc114938312a730a639eb8af445db3ffe0e6`.

Implementation follow-up: [active-file F5 routing](../file-based-apps.md) adds the user's marker/project-membership rules in repository-owned modules and a manifest entry wrapper. It shipped in **11.7.18002**, and all four issue acceptance criteria are fulfilled; see the [completion review](2026-11-03-file-based-app-release.md#issue-11-completion-review). The sections below retain the original investigation's explicit-configuration scope and evidence.

## Finding

File-based apps can use the existing netcoredbg launch path: build the `.cs` file with the .NET SDK into a known directory, then launch its managed DLL through `type: "coreclr"`. This needs no additional changes to `dotnet/vscode-csharp` or `Samsung/netcoredbg`, and no user-maintained `.csproj` or `.sln`. The initial experiment used an explicit build task and launch configuration. The subsequently shipped F5 wrapper creates the build and launch programmatically, without those workspace configuration files.

The existing distribution already has an upstream integration overlay in [`scripts/variant/overlay.py`](../../scripts/variant/overlay.py). Here, “without upstream changes” means retaining that existing distribution and adding no new upstream source edits for file-based debugging.

The initial recommendation was to document the task/configuration route and add a file-based fixture to the release gate, with an optional companion command later. The subsequent implementation delivered active-file F5 inside this distribution, followed by installed-release editor verification and publication. The [release record](2026-11-03-file-based-app-release.md) documents that completed work separately from this initial probe.

## Why an enablement setting is insufficient

The upstream SDK discussion contains a useful correction: on March 26, 2026, the implementer clarified that automatic file-based debugging, including a `dotnet` configuration with `projectPath: "file.cs"`, was implemented in C# Dev Kit. Moving the SDK run-API/executable-path integration into the base C# extension would be additional work. Earlier comments claiming that base C# alone supported this configuration were retracted. See the [correction](https://github.com/dotnet/sdk/issues/49224#issuecomment-4136041135) and [explanation of the missing integration](https://github.com/dotnet/sdk/issues/49224#issuecomment-4136366064).

Current upstream source was also checked at commit `9ff52889564d03d7d072629b2c43f13b8024ced1`, rather than relying only on that historical discussion. Its `dotnet` provider uses Dev Kit's brokered debug service when available, then workspace debug information as a fallback. A fully specified `coreclr` launch takes a different path: the base configuration provider resolves its environment/options without requiring project discovery. The workspace provider inherits that resolution; its project lookup is used for generating configurations. This makes an explicit DLL launch suitable for a workspace containing only a C# file. Sources: [`dotnet` provider](https://github.com/dotnet/vscode-csharp/blob/9ff52889564d03d7d072629b2c43f13b8024ced1/src/shared/dotnetConfigurationProvider.ts), [base configuration provider](https://github.com/dotnet/vscode-csharp/blob/9ff52889564d03d7d072629b2c43f13b8024ced1/src/shared/configurationProvider.ts), [workspace provider](https://github.com/dotnet/vscode-csharp/blob/9ff52889564d03d7d072629b2c43f13b8024ced1/src/shared/workspaceConfigurationProvider.ts).

The same resolution structure was checked in stable `v2.160.4` (`87fca8f19e800a439147d8bc139deaf32092deb3`) and the latest listed prerelease `v11.7.18-prerelease` (`1c27e135b5dada55a240e4a504bafa759ec578e8`). The tested distribution uses that latter C# tag; current `main` is additional source evidence, not the identity of the tested package.

This repository's overlay advertises only `coreclr` and points its adapter executable at the bundled netcoredbg. Adding a `type: "dotnet"` example or installing Dev Kit is therefore not an enablement mechanism for this variant. A new SDK launch-discovery integration is unnecessary for the explicit DLL route.

## Reproducible editor configuration

The stable SDK minimum for building a file-based app is **.NET SDK 10.0.100**. See [`dotnet build` documentation](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-build#examples). The research used SDK **10.0.402** and runtime **10.0.13** on Windows ARM64.

Copy [`app.cs`](file-based-apps-2026-11-03/example/app.cs) and [`global.json`](file-based-apps-2026-11-03/example/global.json) into a new empty folder. Open that folder in the editor. The supplied `global.json` selects an installed stable .NET 10 SDK from the latest available feature band; it avoids accidentally selecting an installed .NET 11 preview. It is an SDK selector, not a project file.

```csharp
int answer = 40;
answer += 2;
Console.WriteLine($"ANSWER={answer}");
```

Install or enable the matching **C# (with netcoredbg)** distribution. Copy [`tasks.json`](file-based-apps-2026-11-03/example/tasks.json) and [`launch.json`](file-based-apps-2026-11-03/example/launch.json) into the folder's `.vscode` directory. These files are stored outside `.vscode` in this report so that they remain visible repository examples.

The task executes:

```text
dotnet build app.cs --configuration Debug --output .file-based-debug/app
```

The launch configuration supplies:

```json
{
  "name": "Debug file-based app with netcoredbg",
  "type": "coreclr",
  "request": "launch",
  "preLaunchTask": "Build file-based app for netcoredbg",
  "program": "${workspaceFolder}/.file-based-debug/app/app.dll",
  "cwd": "${workspaceFolder}",
  "args": [],
  "console": "internalConsole",
  "stopAtEntry": false
}
```

Save `app.cs`, put a breakpoint on `answer += 2;`, select **Debug file-based app with netcoredbg**, and press F5. Inspect `answer` before and after Step Over; expected values are `40` and `42`. Expected output is `ANSWER=42`. The program and build input are fixed paths, so opening `launch.json` or another editor tab cannot accidentally change which file is launched. Add `.file-based-debug/` to the consuming workspace's `.gitignore`.

The task uses `type: "process"` with separate arguments, as supported by [VS Code tasks](https://code.visualstudio.com/docs/debugtest/tasks#custom-tasks). No shell-specific quoting or `${env:TEMP}` layout is needed. The supplied configuration uses the existing adapter and requires no separate debugger path setting.

The SDK internally synthesizes a project for the build; users do not create or maintain it. `--output` avoids depending on the SDK's private, hashed temporary cache layout. Keep the DLL, PDB, `.deps.json`, `.runtimeconfig.json`, and dependencies together. This behavior is described in the [.NET 10 SDK file-app design](https://github.com/dotnet/sdk/blob/v10.0.100/documentation/general/dotnet-run-file.md).

## Observed debugger results

The experiment used the ARM64 debugger archive from the published [C# v11.7.18 / netcoredbg 3.2.0-1092 distribution](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r1). Its SHA-256 was `09746c136b177fe5a2e7ee4f558f051169d7322227d525ac2b919aba7e6be58e`; the extracted executable hash is recorded in [provenance](file-based-apps-2026-11-03/evidence/provenance.json).

| Case | Result | Evidence |
| --- | --- | --- |
| File-based `app.cs`, default Debug build, no extra MSBuild properties | Passed | [Result](file-based-apps-2026-11-03/evidence/fileapp.result.json), [DAP trace](file-based-apps-2026-11-03/evidence/fileapp.dap.jsonl) |
| Fresh copy of the exact documented example, source/output paths containing spaces | Passed; `global.json` selected SDK 10.0.402 | [Result](file-based-apps-2026-11-03/evidence/example.result.json), [DAP trace](file-based-apps-2026-11-03/evidence/example.dap.jsonl), [build output](file-based-apps-2026-11-03/evidence/example-default-build.txt) |
| Same source built as an ordinary .NET 10 project | Passed | [Result](file-based-apps-2026-11-03/evidence/project.result.json), [DAP trace](file-based-apps-2026-11-03/evidence/project.dap.jsonl) |

Each session hit the source breakpoint at line 2, inspected local `answer=40`, evaluated `answer + 2` as `42`, stepped to line 3, observed `answer=42`, printed `ANSWER=42`, and exited with code 0. The fresh example also produced a portable PDB (`BSJB` metadata signature). No `.csproj`, `.sln`, or `.slnx` was present in the file-app source tree. The separate project is only the regression control.

An initial exploratory build explicitly disabled AOT and optimization and selected portable symbols. The reported default-build and fresh-example sessions then passed without those overrides. Thus the example does not depend on them. The project control is a focused .NET 10 sanity check; the full existing .NET 8/10 release matrix was not rerun for documentation changes.

The [evidence README](file-based-apps-2026-11-03/evidence/README.md) contains reproduction instructions and the standalone DAP client's source. Paths in archived logs were normalized; binaries, SDK caches, and build outputs are omitted. These are direct DAP sessions against the distributed debugger archive, not sessions launched through an installed VSIX or editor UI.

## Options considered during the initial investigation

| Approach | Additional upstream source edits | Assessment |
| --- | --- | --- |
| Build task + explicit `coreclr` DLL launch | None | Initial recommendation; verified with the existing adapter contract and documented in this report. |
| Companion extension: build then call `debug.startDebugging` | None | Proposed for a **Debug current C# file** command, saved source outside a workspace, or fewer configuration files. The later implementation uses owned modules inside this distribution instead of a separate extension. |
| `dotnet` configuration with `projectPath` set to `.cs` | Not a supported shortcut in this variant | Automatic discovery belongs to a different integration path; the variant advertises only `coreclr`. |
| Start independently and attach | None at the adapter level | Possible fallback, but early breakpoints require the app to wait and users must select the correct process. Less suitable for the requested launch experience. |
| Launch `dotnet run app.cs` as the debuggee | Unproven | Launches the SDK CLI before the application; do not assume child-process debugging or early breakpoint behavior. |

A companion extension can capture and save the active source URI once, invoke `dotnet build` with an absolute source path and a unique output directory, wait for a successful exit, and call `vscode.debug.startDebugging(folder, { type: 'coreclr', request: 'launch', program: dllPath, cwd: sourceDirectory, ... })`. The public [VS Code debug API](https://code.visualstudio.com/api/references/vscode-api#debug) accepts a launch object, so `launch.json` is optional for that design. The existing C# variant would still own the adapter factory. VS Code permits only one [adapter descriptor factory per debug type](https://code.visualstudio.com/api/references/vscode-api#debug.registerDebugAdapterDescriptorFactory), so the companion must not register a second `coreclr` factory.

Multiple configuration providers can coexist, but their [resolve order is arbitrary](https://code.visualstudio.com/api/references/vscode-api#DebugConfigurationProvider). Intercepting an empty F5 configuration is therefore unreliable: upstream's provider could abort first. A dedicated command/editor button that submits a completed launch object avoids depending on provider order.

That helper should use the same SDK root/architecture as the adapter, respect the source directory's `global.json`, and isolate outputs by full source path. It should stop on a failed build and avoid treating every `.cs` file inside an existing project as a standalone app. These are implementation recommendations, not capabilities verified by this research. The SDK run-API could eventually provide richer launch discovery; it is unnecessary for the minimal deterministic build/launch flow.

## Initial probe limits and subsequent completion of #11

- This is managed DLL debugging. File-based apps' Native AOT publish defaults do not make native executables suitable for netcoredbg. Use the Debug build output from this example, rather than a `dotnet publish` native executable. See the [SDK file-app design](https://github.com/dotnet/sdk/blob/v10.0.100/documentation/general/dotnet-run-file.md).
- A source directive or inherited `Directory.Build.props`/`.targets` can alter the assembly name, debug symbols, target framework, or output layout. Adapt a fixed example for those cases; a helper must inspect or control the actual output. NuGet directives can require restore/network access.
- The explicit task/launch example needs a saved file and an opened folder. Automatic F5 was outside the initial probe and was subsequently implemented in the distribution. Web launch-profile parity, Hot Reload, and interactive-terminal behavior remain outside that flow. `internalConsole` is sufficient for this noninteractive fixture.
- The initial local probe verifies debugger protocol behavior on one host. Its evidence does not establish installed-extension editor behavior or an eight-platform file-based-app matrix. Later [F5 evidence](file-based-apps-2026-11-03/f5-evidence/README.md) and [installed-release evidence](file-based-apps-2026-11-03/release-evidence/README.md) record the separate editor checks.

At the end of the initial probe, installed-distribution and existing-project editor checks were still needed for issue acceptance. Both subsequently passed with the unchanged CI-built `11.7.18002` VSIX, and the eight-target release passed its native and extracted-VSIX gates before publication. The [completion review](2026-11-03-file-based-app-release.md#issue-11-completion-review) maps all four original acceptance criteria to the retained evidence.

For future coverage, a dedicated .NET 10 file-based DAP fixture in every native and extracted-VSIX job would extend the current editor and project-based .NET 8/10 checks. Such a fixture should create no user project and assert source breakpoint binding, variables, stepping, output, and exit. SDK-version failures, paths with spaces, `#:package`, changed assembly names, and inherited build settings are useful expansion cases. This recommendation is follow-up coverage work, not an unmet original acceptance criterion.

The initial DAP investigation changed no production overlay, release workflow, or upstream source. Subsequent implementation and release changes are recorded in the release report. Research documentation alone is outside the release recipe fingerprint, so this completion update does not request a new package build.
