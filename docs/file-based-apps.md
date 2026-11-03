# Debug the active C# file with F5

Active-file F5 support is available starting with **11.7.18002** of [C# (with netcoredbg) on Open VSX](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg). It uses the existing extension ID, `dotnetdev-kr-custom.csharp-with-netcoredbg`. Earlier packages without the entry wrapper can use the [explicit build-task/launch configuration](research/2026-11-03-file-based-app-debugging.md) from the initial investigation. The upstream-preserving `dotnetdev-kr-custom.csharp` distribution is independent.

Open a saved `.cs` file, put keyboard focus in its editor, and press **F5** while no debug session is active. A dirty file is saved before classification. There is no need to add `.vscode/launch.json` or a project file for a file-based app. The command is also available as **C# (netcoredbg): Debug Active File**.

## Package availability and changes

An official update retains the same extension ID and receives a new packaging revision under the [existing version policy](../README.md#4-tags-versions-and-provenance). The release must pass the native and extracted-VSIX gates on all eight targets before Open VSX publication. A locally modified VSIX carrying an existing version is a manual test package, not evidence that the update is available from the registry.

Release `11.7.18002` passed those gates, and all eight platform-specific latest feeds returned that version after publication. The [release record](research/2026-11-03-file-based-app-release.md) preserves the workflow and independent public download checks. It also records the [completed acceptance review for issue #11](research/2026-11-03-file-based-app-release.md#issue-11-completion-review).

The follow-up **11.7.18003** release fixes retry after errors. Its [release record](research/2026-11-03-file-based-app-retry-release.md) preserves the 29 successful CI jobs, installed-package retry checks, and public package verification. **11.7.18004** adds Web startup support and 21 FBA snippets; the [new release record](research/2026-11-03-file-based-web-snippets-release.md) preserves its eight-platform gates, actual installed-package checks and public verification.

Compared with a package without this feature, the new behavior is automatic active-file classification and FBA build/launch through F5. Existing selected project configurations and Continue during a debug session retain their behavior. No workspace `launch.json`, `tasks.json`, or manual-test sample projects are installed by the extension.

## Web startup support in 11.7.18004

Release **11.7.18004** adds ASP.NET Core startup support, following the November 3 isolated **LOCAL WEB TEST** prototype. Its implementation and verification scope are recorded in the [Web bootstrap investigation](research/2026-11-03-file-based-web-bootstrap.md) and [release record](research/2026-11-03-file-based-web-snippets-release.md).

The same build invocation returns evaluated Web SDK/framework metadata. For a managed Web server, the wrapper reads the original source's adjacent `sample.run.json`, or `Properties/launchSettings.json` when present, and uses the first supported `Project` profile. It applies environment variables, application URLs and command-line arguments. `launchBrowser: true` opens the profile's launch URL after the debugger reports a listening address; `false` or an omitted value in an existing profile leaves the browser closed.

Without a profile, an in-memory development profile enables browser launch and supplies dynamic HTTPS/HTTP ports when endpoint settings are absent. HTTPS checks the development certificate using the selected SDK and asks before creating or trusting it. Cancellation during certificate preparation stops this launch and permits another F5. HTTP-only endpoint settings in the profile, environment or command-line arguments skip certificate preparation. No project, launch configuration or profile file is generated in the source directory.

Application code and appsettings can override Kestrel endpoints or certificates after this preparation, so those custom settings are not inferred in advance. Linux certificate trust depends on the installed .NET/OS trust tooling and browser stores; a failed trust check stops HTTPS preparation, while an explicit HTTP profile can run without it. The SDK's own first-use certificate generation is separate from the extension's explicit trust confirmation.

The package README also removes the inherited Dev Kit installation recommendation. Extension recommendation settings are unchanged. Existing project-file routing and the earlier retry fix remain in place.

The same release includes [21 FBA snippets](file-based-app-snippets.md), including Console/Web starters, shebang and managed-publishing directives, source paths, configuration, API endpoints, JSON source generation, and periodic work. It preserves the existing 42 upstream C# snippets. The earlier **LOCAL FBA SNIPPETS TEST** package remains a separate pre-release test artifact.

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

This flow launches the source file as a managed app; it does not debug a Native AOT executable. Application output uses the Debug Console. Interactive stdin and Hot Reload are outside this flow. Web-server launch-profile support requires `11.7.18004` or later. F5 continues to use the editor's normal Continue action during an existing debug session. User keyboard-shortcut overrides retain their normal precedence.

## Retrying after a build error

A compilation error prevents the debugger from starting. **11.7.18003 fixes retry after build or save errors:** error notifications display without waiting for dismissal, so failed output is cleaned up and the next F5 can save and rebuild the corrected file even while an earlier notification remains open. Update the extension and reload the editor window to load the corrected runtime.

In the affected **11.7.18002** package, an open **C# file debugging failed** notification keeps that file's previous command pending. Until updating, close the notification, including its entry in the notification center, then press F5 again. Regression tests for the fix retain an unresolved notification while retrying after build and save failures.

## Implementation and validation

Repository-owned modules live in [`scripts/variant/file-based-apps`](../scripts/variant/file-based-apps). Packaging adds `.netcoredbg/entry.cjs`, `runtime.cjs`, `classify.cjs`, and (starting in `11.7.18004`) `web.cjs`; updates manifest `main` to the wrapper; preserves the original entry in `netcoredbgBuild.upstreamMain`; and registers the command, activation event, and F5 binding. The wrapper registers the command and calls the original upstream activation function, preserving its returned API and other exports. There are no additional upstream JS/TypeScript source replacements for this feature. It uses the existing bundled debugger and language service implementations, and the existing `coreclr` adapter factory remains the sole adapter owner.

The release preflight runs the classifier, runtime, and wrapper tests. VSIX verification checks the entry point, original upstream entry, command/binding, and exact owned module bytes. Existing native and extracted-VSIX project-based debugger gates remain enabled.

Local validation on Windows ARM64 covered actual MSBuild membership for included, excluded, ancestor, and conditional multi-target cases. The real runtime command, classifier, .NET SDK 10.0.402 build, and distributed netcoredbg passed breakpoint, locals, evaluation, stepping, changed-value, output, and exit checks. An initial **real VS Code 1.144.1 extension-host run** passed FBA and existing selected-project debugging with the published variant plus the new owned entry/modules, keeping the original compiled C# extension unchanged. [Initial evidence and scopes](research/file-based-apps-2026-11-03/f5-evidence/README.md) distinguish those local checks from release verification.

The unchanged **CI-built 11.7.18002 Windows ARM64 VSIX** was then installed normally in an isolated editor and passed ten assertions for FBA and existing selected-project debugging. Its hash matches the public Open VSX download. These automated editor tests verified the F5 manifest and invoked its registered command through the real editor API; no physical keypress was synthesized. The [release evidence](research/file-based-apps-2026-11-03/release-evidence/README.md) records this installed-package check, the separate eight-platform native/extracted-VSIX debugger matrix, and verified publication. The matrix does not establish eight-platform FBA editor coverage.

The unchanged **11.7.18003** CI package also passed ten [installed-editor assertions](research/file-based-apps-2026-11-03/retry-evidence/editor/README.md), including a real compiler failure followed by a successful same-file retry while its error notification remained visible. Same-file Web SDK conversion and selected-project debugging passed as well. This remains Windows ARM64/VS Code API-command coverage; Cursor and physical F5 input were not exercised. The intermittent Web SDK resource-glob failure and reported editor SDK/property refresh delays remain separate investigations.

Run the focused logic tests with Node 22 or later:

```text
node --test scripts/variant/file-based-apps/test-*.cjs
python3 -m unittest discover -s scripts/variant -p 'test_*.py' -v
```
