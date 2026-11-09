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

The current development recipe retries temporary-output deletion up to three times for transient filesystem errors. If deletion still fails, **C# File Debugging** records the failure and retains ownership for another attempt; each later file-debug command retries at most one previously failed output. Running sessions keep their output. These retries do not replace the original launch result or error, and do not impose a time limit on an individual filesystem operation. Recovery tracking lasts for the current extension host; cleanup after a crash or reload remains separate work. This cleanup improvement has not yet been assigned a published release version.

This flow launches the source file as a managed app; it does not debug a Native AOT executable. Application output uses the Debug Console. Interactive stdin and Hot Reload are outside this flow. Web-server launch-profile support requires `11.7.18004` or later. F5 continues to use the editor's normal Continue action during an existing debug session. User keyboard-shortcut overrides retain their normal precedence.

## Retrying after a build error

A compilation error prevents the debugger from starting. **11.7.18003 fixes retry after build or save errors:** error notifications display without waiting for dismissal, so failed output is cleaned up and the next F5 can save and rebuild the corrected file even while an earlier notification remains open. Update the extension and reload the editor window to load the corrected runtime.

In the affected **11.7.18002** package, an open **C# file debugging failed** notification keeps that file's previous command pending. Until updating, close the notification, including its entry in the notification center, then press F5 again. Regression tests for the fix retain an unresolved notification while retrying after build and save failures.

The current development recipe also reports when the editor returns `false` instead of starting a netcoredbg session. Inspect **C# File Debugging**, **C#**, and **Debug Console** output for the underlying reason, then retry. The failed launch releases its temporary output and pending operation while its notification remains open. Cancelling the file-debugging progress while a declined start is pending remains quiet. This diagnostic improvement has not yet been assigned a published release version; it does not identify the cause of every declined launch.

The development recipe also releases the file command when its progress is cancelled while the editor's start request is pending. That request remains tracked: if its session starts later, only the session matching that run's output, program and debugger type is stopped. Output stays available until that session's termination event arrives, including when the stop request completes first. If stopping fails, an error asks you to stop the session manually and its output is preserved. You can run **C# (netcoredbg): Debug Active File** again while an earlier start is still pending; its eventual termination cannot remove the retry's output.

Normal Continue/Stop controls apply once a successful launch has finished its progress. A start request that never settles, or a successful start whose session event never arrives, retains output for safety. Actual request drain and unknown output are not force-completed by a foreground deadline. This behavior is not yet assigned a published release version.

The development recipe distinguishes editor acceptance from an observed session start. If the start API returns `true` before an exact owned session event is observed, **C# File Debugging** records one accepted-but-unconfirmed entry with its program and retained output directory. A matching late start records confirmation once; unrelated or duplicate events do not confirm another run. The command still returns the editor's accepted result, and this diagnostic does not prove that a process is absent or that output is safe to delete. A separate run can use fresh output while the earlier launch remains tracked.

When disposal retains a launch, the output records whether its owned start request, including queued admission, is pending, accepted, declined or rejected, whether an exact session was observed, and the retained output directory. Pending or rejected requests can include admission work before API dispatch. A session handle permits the existing exact-session Stop path; no observed handle means no speculative Stop. Missing start or termination events can still leave drain pending indefinitely. These entries add no timer, notification, cancellation or cleanup policy. Logging is best effort: delivery and ordering are not guaranteed, and a diagnostic failure does not replace the launch result.

The [November 4 cancellation control](research/cancel-session-2026-11-04/README.md) records the local Windows ARM64 real-API check, including output preservation between stop completion and the termination event. It distinguishes injected progress cancellation and direct runtime loading from installed-command and VSCodium qualification.

The current development recipe shares a **five-minute preparation deadline** across SDK discovery, project membership evaluation (including ancestor projects and target frameworks), SDK checks, and compilation through DLL/PDB verification. Each subprocess no longer receives a fresh preparation budget. **C# File Debugging** records phase starts, outcomes, phase durations and total elapsed milliseconds using a monotonic clock. A preparation timeout reports its phase and cumulative elapsed time. Explicit user cancellation remains quiet.

A separate **five-minute editor-save deadline** applies only when the captured document is dirty. It starts at `Saving C# file`, checks elapsed time before the save call and after a normal reply, and ends as soon as a timely reply is accepted. A delayed timer callback cannot accept an over-budget `true` or `false` reply. A rejected save keeps its original error unless cancellation or timeout has already been selected. The SDK preparation budget begins only after a successful save and subsequent text retrieval, and debugger handoff retains its separate budget. These defaults are conservative policies, not calibrated latency targets or release-performance qualification.

A save timeout returns `false`, closes the file-debugging progress and reports the save phase once. It does **not cancel the underlying editor save**: that operation may still finish writing the document. Another command for the same file returns the previous result without starting a competing save or build until the original save actually settles. Other files can proceed independently. A late result cannot start SDK or debugger work for the timed-out run; after actual drain, a corrected run gets fresh save, SDK and handoff budgets. Disposal also continues waiting for the original save, including any late rejection.

A separate **five-minute debugger handoff deadline** covers the owned file-app launch at `Starting netcoredbg`. It starts before preparing and dispatching the editor start request. Monotonic elapsed time is checked before the actual API call and after a normal reply, so a delayed timer callback cannot accept an over-budget `true` or `false` reply. A timely reply ends this deadline; later logging and workflow bookkeeping do not count toward it. A rejected start preserves its original error unless cancellation or timeout has already been selected. The five-minute default is a conservative policy, not a calibrated latency target or release-performance qualification.

Verified Web apps also receive a separate **five-minute budget for noninteractive Web preparation**. It covers launch-profile reads, temporary port reservation, the initial HTTPS certificate check and post-trust verification. The budget pauses explicitly before certificate consent and stays paused through the trust request. Verification resumes only the remaining time: user interaction does not reset earlier preparation cost. Old queued timer callbacks cannot expire a resumed or completed budget. A timeout reports noninteractive elapsed time separately from the phase log's total elapsed time, which includes interaction. This is a conservative default, not a measured latency threshold.

A normal Web-provider reply is checked against the remaining budget before that budget closes; subsequent profile-root validation, logging and debugger handoff have their existing policies. A fatal provider rejection retains its original error unless timeout or cancellation has already won. Timeout releases foreground progress while unfinished owned provider, child or port-close work remains observed, with output and disposal retained according to that work's actual settlement. Explicit cancellation stays quiet. Consent and trust are exempt from this new active-time budget, while the existing individual .NET process timeout still applies during trust; this does not promise unlimited OS trust or preempt operating-system requests.

Profile input reads retain their existing early-failure behavior: if one read fails, the logical Web workflow may finish while a pure sibling input read remains pending. Its original result or rejection stays observed and cannot resume parsing, SDK work or output use. This exception does not authorize discarding an active process, port or other owned resource. It also does not claim that every operating-system read has finished when foreground progress or the logical workflow ends.

Cancellation or a save, SDK or Web preparation expiry returns `false` and closes the file-debugging progress while unfinished owned work remains observed in the background. The output records `Foreground cancelled` or `Foreground timed out` with the phase and explains that this file cannot retry until its workflow settles. Repeating the command for the same file returns its previous result without starting another save or build. Other files can proceed independently. A later `Phase drained after ...` entry records actual workflow settlement; the file can then start a corrected run with fresh applicable deadlines. Owned output and disposal remain pending while that owned work requires them, and a late result cannot resume the cancelled launch. Completed workflow results take precedence over later progress-provider failures.

A handoff timeout also returns `false` with one phase-specific error, while uncertain editor requests remain tracked. This is a distinct retry policy: after the foreground workflow drains, another run can use fresh output even while the original editor request is pending. If an owned session starts late, only that exact session is stopped; Stop acknowledgement alone does not authorize output deletion. Its output remains until safe termination, and the original API result can still keep disposal pending after the foreground has returned. The timeout does not prove the original request finished, establish debugger readiness or bound the lifetime of a successfully launched session.

The SDK preparation timer is disarmed before Web settings and before delegating an included file to existing project debugging. Save, Web preparation and handoff have the separate budgets above; output cleanup, interactive waiting and session lifetime have no new total phase bound. Once the existing selected-project debug command has been dispatched, its editor-owned completion is still awaited because this file controller owns no corresponding project session. Cancellation requests do not authorize early output cleanup: the direct child and its streams must close, or the relevant owned operation must settle. Foreground cancellation and deadlines require a responsive event loop; synchronous blocked work and operating-system requests have no hard wall-clock bound. Actual drain and disposal can remain pending indefinitely. This is not a process-tree cleanup guarantee or measured release-performance threshold, and the improvement has no published release version yet.

The [preparation deadline controls](research/preparation-deadline-2026-11-04/README.md) retain the logic/native-child checks and a real .NET SDK timeout/retry control, with its injected clock and mocked editor scope stated explicitly.

The development recipe also preserves recoverable cleanup failures across extension-host restarts. Only after a run is known to be terminal and ordinary deletion fails, its remaining output can be moved to a dedicated terminal cleanup queue with a versioned receipt. A later activation checks at most 32 queue entries and attempts one valid cleanup in the background, without delaying a new file command. Partial deletion leaves the receipt available for another activation. Running sessions, pending editor starts, old unmarked run directories and incomplete staging entries are preserved; age or a missing process is not evidence that output is safe to remove.

Recovery accepts only the fixed output child of a valid queue entry. Links/junctions, damaged or unfamiliar records, and unexpected sibling files are skipped. If an output cannot be moved and published to the queue, same-host retry remains available but automatic recovery after a restart is not guaranteed. This is a local-storage recovery mechanism, not protection against malicious concurrent filesystem replacement; individual filesystem operations also have no wall-clock bound. Crash/reload behavior in installed VSCodium and full process-tree/Web-port cleanup remain separate qualification work. This recovery improvement is unreleased.

The [terminal recovery record](research/2026-11-04-terminal-output-recovery.md) describes the fixed-path receipt, publication boundaries, concurrent-host race checks and native two-process control. Recovery is one bounded best-effort pass, so it does not guarantee that every queued item will be reached or collected.

## Implementation and validation

The [stability contract](stability-contract.md) separates existing debugger/editor evidence from required VSCodium qualification and defines repeated-workflow, timing and recovery acceptance. Publishing the contract does not qualify an unmeasured target.

The [#18 acceptance-boundary proposal](research/issue-18-acceptance-proposal-2026-11-09.md) compares the original seven unchecked criteria with current evidence and proposed ownership/foreground interpretations. It is pending review and does not approve a scope reduction, complete a criterion or close the issue. Actual F5/menu, native macOS and the existing qualification protocol remain required; #45's original unexplained Pause remains unresolved. The contract's [implemented phase/ownership table](stability-contract.md#implemented-foreground-policies-and-ownership) distinguishes current guardrails from qualification and from actual settlement/readiness guarantees.

Repository-owned modules live in [`scripts/variant/file-based-apps`](../scripts/variant/file-based-apps). Packaging adds `.netcoredbg/entry.cjs`, `runtime.cjs`, `classify.cjs`, and (starting in `11.7.18004`) `web.cjs`; the current development recipe also adds the unreleased `recovery.cjs`. It updates manifest `main` to the wrapper, preserves the original entry in `netcoredbgBuild.upstreamMain`, and registers the command, activation event, and F5 binding. The wrapper registers the command and calls the original upstream activation function, preserving its returned API and other exports. There are no additional upstream JS/TypeScript source replacements for this feature. It uses the existing bundled debugger and language service implementations, and the existing `coreclr` adapter factory remains the sole adapter owner.

The release preflight runs the classifier, runtime, and wrapper tests. VSIX verification checks the entry point, original upstream entry, command/binding, and exact owned module bytes. Existing native and extracted-VSIX project-based debugger gates remain enabled.

Local validation on Windows ARM64 covered actual MSBuild membership for included, excluded, ancestor, and conditional multi-target cases. The real runtime command, classifier, .NET SDK 10.0.402 build, and distributed netcoredbg passed breakpoint, locals, evaluation, stepping, changed-value, output, and exit checks. An initial **real VS Code 1.144.1 extension-host run** passed FBA and existing selected-project debugging with the published variant plus the new owned entry/modules, keeping the original compiled C# extension unchanged. [Initial evidence and scopes](research/file-based-apps-2026-11-03/f5-evidence/README.md) distinguish those local checks from release verification.

The unchanged **CI-built 11.7.18002 Windows ARM64 VSIX** was then installed normally in an isolated editor and passed ten assertions for FBA and existing selected-project debugging. Its hash matches the public Open VSX download. These automated editor tests verified the F5 manifest and invoked its registered command through the real editor API; no physical keypress was synthesized. The [release evidence](research/file-based-apps-2026-11-03/release-evidence/README.md) records this installed-package check, the separate eight-platform native/extracted-VSIX debugger matrix, and verified publication. The matrix does not establish eight-platform FBA editor coverage.

The unchanged **11.7.18003** CI package also passed ten [installed-editor assertions](research/file-based-apps-2026-11-03/retry-evidence/editor/README.md), including a real compiler failure followed by a successful same-file retry while its error notification remained visible. Same-file Web SDK conversion and selected-project debugging passed as well. This remains Windows ARM64/VS Code API-command coverage; Cursor and physical F5 input were not exercised. The intermittent Web SDK resource-glob failure and reported editor SDK/property refresh delays remain separate investigations.

Run the focused logic tests with Node 22 or later:

```text
node --test scripts/variant/file-based-apps/test-*.cjs
python3 -m unittest discover -s scripts/variant -p 'test_*.py' -v
```
