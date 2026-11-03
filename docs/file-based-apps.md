# Debug the active C# file with F5

This integration is specific to **C# (with netcoredbg)** builds containing the active-file entry wrapper. It uses the existing extension ID, `dotnetdev-kr-custom.csharp-with-netcoredbg`. Earlier packages without the wrapper can use the [explicit build-task/launch configuration](research/2026-11-03-file-based-app-debugging.md) from the initial investigation. The upstream-preserving `dotnetdev-kr-custom.csharp` distribution is independent.

Open a saved `.cs` file, put keyboard focus in its editor, and press **F5** while no debug session is active. A dirty file is saved before classification. There is no need to add `.vscode/launch.json` or a project file for a file-based app. The command is also available as **C# (netcoredbg): Debug Active File**.

## Package availability and changes

An official update retains the same extension ID and receives a new packaging revision under the [existing version policy](../README.md#4-tags-versions-and-provenance). The release must pass the native and extracted-VSIX gates on all eight targets before Open VSX publication. A locally modified VSIX carrying an existing version is a manual test package, not evidence that the update is available from the registry.

Compared with a package without this feature, the new behavior is automatic active-file classification and FBA build/launch through F5. Existing selected project configurations and Continue during a debug session retain their behavior. No workspace `launch.json`, `tasks.json`, or manual-test sample projects are installed by the extension.

## How the launch is selected

The first matching rule wins:

| Active file | F5 behavior |
| --- | --- |
| Starts with a shebang (`#!`, optionally after a BOM) | Build and debug this file as a file-based app. |
| Contains a `#:` directive outside comments and string literals | Build and debug this file as a file-based app. |
| Has neither marker, and no `.csproj` exists in its directory or any ancestor through the filesystem root | Build and debug this file as a file-based app. |
| Has neither marker, and all candidate projects exclude the file from their evaluated `Compile` items | Build and debug this file as a file-based app. |
| Is included by any candidate project | Use the existing selected project debugging configuration through normal F5. |

Explicit markers take precedence even inside a project directory. An excluded nearby project does not override inclusion by another project further up the directory tree. For multi-target projects, inclusion in any target framework is sufficient.

The project branch deliberately retains the selected debug configuration. For example, pressing F5 in a library source file can still launch the existing application that references that library. It does not try to run the library's `.csproj` itself. If a configuration has not yet been selected, the editor follows its normal setup/selection flow.

With several projects, check the Run and Debug selector: opening a source file in Project B while Project A's configuration remains selected still launches Project A. Select Project B's configuration to debug that application. Fixing the selector or a manual test workspace's `launch.json` does not change FBA classification or add a new project-selection policy.

Project membership uses MSBuild evaluation, including default items, `Include`, `Exclude`, `Remove`, imported properties/targets, and framework conditions. It does not execute arbitrary build targets to discover items that custom tasks add or remove during target execution. A failed evaluation is reported in **C# File Debugging** output; it is never interpreted as proof of exclusion. Projects in unrelated directories are outside this same-directory/ancestor search.

## Requirements and examples

File-based debugging requires **.NET SDK 10.0.100 or later** and a native SDK architecture matching the installed netcoredbg package. The SDK is selected from the source directory, so its `global.json` is honored. Existing project debugging keeps its own SDK requirements. Evaluating project membership requires MSBuild 17.8 or later (included in .NET 8 SDK).

A plain file outside any project is sufficient:

```csharp
int answer = 40;
answer += 2;
Console.WriteLine($"ANSWER={answer}");
```

Save it as `app.cs`, set a breakpoint on the second line, and press F5. The debugger should stop with `answer == 40`; Step Over changes it to `42`.

Inside a project directory, either marker explicitly requests a file-based app:

```csharp
#!/usr/bin/env dotnet
Console.WriteLine("Standalone file-based app");
```

```csharp
#:property TargetFramework=net10.0
Console.WriteLine("Standalone file-based app");
```

The build runs with the source directory as its working directory, Debug configuration, portable symbols, optimization disabled, and managed output. Each launch has an isolated output directory in extension storage, so names and concurrent sessions cannot overwrite one another. The output is removed after its debug session terminates. NuGet directives can require a package restore.

This flow launches the source file as a managed app; it does not debug a Native AOT executable. Application output uses the Debug Console. Interactive stdin, launch-profile discovery for file-based apps, and Hot Reload are outside this flow. F5 continues to use the editor's normal Continue action during an existing debug session. User keyboard-shortcut overrides retain their normal precedence.

## Implementation and validation

Repository-owned modules live in [`scripts/variant/file-based-apps`](../scripts/variant/file-based-apps). Packaging adds `.netcoredbg/entry.cjs`, `runtime.cjs`, and `classify.cjs`; updates manifest `main` to the wrapper; preserves the original entry in `netcoredbgBuild.upstreamMain`; and registers the command, activation event, and F5 binding. The wrapper registers the command and calls the original upstream activation function, preserving its returned API and other exports. There are no additional upstream JS/TypeScript source replacements for this feature. It uses the existing bundled debugger and language service implementations, and the existing `coreclr` adapter factory remains the sole adapter owner.

The release preflight runs the classifier, runtime, and wrapper tests. VSIX verification checks the entry point, original upstream entry, command/binding, and exact owned module bytes. Existing native and extracted-VSIX project-based debugger gates remain enabled.

Local validation on Windows ARM64 covered actual MSBuild membership for included, excluded, ancestor, and conditional multi-target cases. The real runtime command, classifier, .NET SDK 10.0.402 build, and distributed netcoredbg passed breakpoint, locals, evaluation, stepping, changed-value, output, and exit checks. A separate **real VS Code 1.144.1 extension-host run** passed the same debugger checks with the published variant plus the new owned entry/modules, keeping the original compiled C# extension unchanged. An included project source also launched the existing selected configuration and passed its breakpoint/output/exit checks. That automated editor test verified the F5 manifest and invoked its registered command through the real editor API; no physical keypress was synthesized. [Evidence and scopes](research/file-based-apps-2026-11-03/f5-evidence/README.md) distinguish local checks from the full upstream rebuild and eight-platform release matrix. Local success does not replace the release gates or establish registry publication.

Run the focused logic tests with Node 22 or later:

```text
node --test scripts/variant/file-based-apps/test-*.cjs
python3 -m unittest discover -s scripts/variant -p 'test_*.py' -v
```
