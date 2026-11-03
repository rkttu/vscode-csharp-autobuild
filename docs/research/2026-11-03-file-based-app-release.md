# Active-file F5 release record

Date: November 3, 2026. Feature: [issue #11](https://github.com/rkttu/vscode-csharp-autobuild/issues/11). Behavior and requirements: [active-file debugging](../file-based-apps.md).

## Implementation and package scope

The `dotnetdev-kr-custom.csharp-with-netcoredbg` distribution adds three repository-owned CommonJS modules and manifest registration. Its entry wrapper registers active-file F5 support and calls the original C# activation function, preserving the upstream API. This feature adds no upstream JS/TypeScript source replacements and keeps the existing debugger adapter and language service implementations.

The first applicable rule chooses file-based execution: a first-line shebang; a real `#:` directive; no project in the same directory or any ancestor through the filesystem root; or exclusion from every candidate project's evaluated Compile items. Inclusion by any candidate project selects the existing project debugging configuration. Evaluation errors stop with a diagnostic. Multi-target project membership is checked in each target framework.

FBA launch uses the source directory's selected SDK, requires .NET SDK 10.0.100 or later with the package's native architecture, and builds managed Debug output with portable symbols. The extension stores each session's output separately and removes its own output on termination. It does not install a workspace launch configuration. Project files keep the selected launch configuration, including when it starts an application referencing the current library file.

## Local verification and manual feedback

Final local checks passed 28 Node tests, 33 variant Python tests, and 23 validation Python tests. Six POSIX process-group cleanup tests were skipped on Windows. There were no test failures, and the whitespace check passed.

Actual SDK/MSBuild checks covered default inclusion, Compile Remove, ancestor inclusion, and conditional multi-target membership. Direct runtime/SDK/netcoredbg sessions passed breakpoints, locals, expression evaluation, Step Over, output, and normal exit. A real VS Code 1.144.1 Windows ARM64 extension-host test passed both FBA execution and the existing selected-project configuration. [Preserved evidence](file-based-apps-2026-11-03/f5-evidence/README.md) records scopes, hashes, diagnostics, and the initial installed-editor startup failures followed by the successful portable-editor run.

The user also tested an isolated installed LOCAL VSIX. Standalone, shebang, directive, excluded-source, and ordinary-project cases worked. The `03-excluded/Program.cs` report was reproduced: the file correctly classified as project-owned, but the only selected launch configuration started `04-project`, so a breakpoint in `03-excluded` could not hit. Adding and selecting a `03-excluded` configuration made its breakpoint, local `40`, Step Over to `42`, output, and exit pass. The extension and VSIX required no correction for that report; the manual workspace gained a missing launch/task configuration and clearer instructions.

Local test packages retained the base version and carried LOCAL branding. They are not registry release artifacts. A regular candidate must receive a new packaging revision, rebuild from the pinned source inputs, and pass the full eight-target native and extracted-VSIX release gates.

## Publication tracking

The requested release uses C# `v11.7.18-prerelease` at `1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at `9744e1f051866215611b8440c638042aa2aa2f72`, matching the local validation inputs. The release workflow determines the next unreserved packaging revision.

The implementation was committed and pushed to `main` as [`d66f36ebc86c57e62973aa8a836e3339820cbb04`](https://github.com/rkttu/vscode-csharp-autobuild/commit/d66f36ebc86c57e62973aa8a836e3339820cbb04). The [authorized release run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41585795220) selected candidate `11.7.18002`, packaging revision 2, fingerprint `74abeaff6a8f21736805c80d60a916f5bae86aea3e6c642a05798b7addfa5a3c`.

The first run's discovery and F5 preflight passed, followed by seven native targets. While the final native target was running, a controlled Git checkout reproduced a release-verification issue: the Linux-packaged CJS modules have LF endings, but a Windows checkout with `core.autocrlf=true` changes their bytes to CRLF. All three exact module comparisons fail in that checkout and pass with `core.autocrlf=false`.

The Windows extracted-VSIX job now sets `core.autocrlf=false` before its first checkout, matching the existing native-validation policy. The verifier's exact-byte contract is retained. The first run was stopped before publication so the corrected workflow can run the complete candidate again. This is a verification-environment correction, not a change to F5 runtime behavior. [Controlled checkout evidence](file-based-apps-2026-11-03/f5-evidence/line-ending-repro.json) records the result.

Final native/extracted-VSIX validation and registry publication are pending the corrected run. This section will record its source commit, workflow result, and public readback once complete; local checks and a selected candidate version alone do not establish publication.
