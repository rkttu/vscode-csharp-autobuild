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

## Published release

The release uses C# `v11.7.18-prerelease` at `1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at `9744e1f051866215611b8440c638042aa2aa2f72`, matching the local validation inputs. The release workflow selected packaging revision 2.

The implementation was committed and pushed to `main` as [`d66f36ebc86c57e62973aa8a836e3339820cbb04`](https://github.com/rkttu/vscode-csharp-autobuild/commit/d66f36ebc86c57e62973aa8a836e3339820cbb04). The [authorized release run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41585795220) selected candidate `11.7.18002`, packaging revision 2, fingerprint `74abeaff6a8f21736805c80d60a916f5bae86aea3e6c642a05798b7addfa5a3c`.

The first run's discovery and F5 preflight passed, followed by seven native targets. While the final native target was running, a controlled Git checkout reproduced a release-verification issue: the Linux-packaged CJS modules have LF endings, but a Windows checkout with `core.autocrlf=true` changes their bytes to CRLF. All three exact module comparisons fail in that checkout and pass with `core.autocrlf=false`.

The Windows extracted-VSIX job now sets `core.autocrlf=false` before its first checkout, matching the existing native-validation policy. The verifier's exact-byte contract is retained. The first run was stopped before publication, and the corrected workflow reran the complete candidate. This is a verification-environment correction, not a change to F5 runtime behavior. [Controlled checkout evidence](file-based-apps-2026-11-03/f5-evidence/line-ending-repro.json) records the result.

The correction was pushed as [`10b0e9ec62227567521dea0ef8a0d4d212eebedd`](https://github.com/rkttu/vscode-csharp-autobuild/commit/10b0e9ec62227567521dea0ef8a0d4d212eebedd). The [corrected release run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41587850063) completed successfully with all 29 jobs passing: eight native source/DAP validations, eight VSIX packages, eight extracted-VSIX validations, and the associated discovery, preflight, aggregation, and publication jobs. Each native and extracted-VSIX target tested .NET 8 and .NET 10 with the required upstream scenarios. This matrix establishes debugger protocol coverage; it is not an eight-platform editor UI test.

Version **11.7.18002**, packaging revision 2, is published on [Open VSX](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg) and in the [GitHub release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r2). GitHub finalization occurred on November 3, 2026 at 15:58 KST. The final fingerprint is `2dd73f55f989ebff3ef5781c4d879f4a2dac2267c4c7071bc2109ca49bfda1c6`, with recipe `bc6da214c972519227f1af65593f4eb961430371f2d631b81f61a7c3c337def2`.

The publisher downloaded every platform from Open VSX and matched its complete VSIX hash to the tested release manifest. An independent readback then confirmed all eight exact-version records and all eight platform-specific latest feeds at `11.7.18002`. It downloaded the public Windows ARM64 package again, verified its whole-file hash, matched the three owned CJS modules to canonical Git bytes at `10b0e9e`, and matched all 16 debugger payload files to the published validation manifest. The Windows ARM64 VSIX SHA-256 is `932045fdd0a55b66e8d54a8bf71f32721e2ce180c46bc5e8be21fe905630ef21`.

The actual CI-built Windows ARM64 VSIX was also installed unchanged into an isolated extension directory and passed ten real-editor assertions for FBA and selected-project debugging. No target extension injection or target development-path override was used. As with the earlier editor checks, the test verified the F5 manifest and invoked its command through VS Code rather than synthesizing a physical keypress. The original compiled C# entry retained SHA-256 `b9b22a4523458d4f5e8763e87f84b4cc3c3a60be0321a01fef10c0cb445aecea`; the rebuilt debugger has its own validated hashes. A nonfatal transport read error after the first session terminated remains recorded; both sessions and the host exited normally.

[Release evidence](file-based-apps-2026-11-03/release-evidence/README.md) contains the job summary, public manifests, publication status, independent registry readback, and the actual installed-CI-package editor test. The release's `native-validation-evidence.zip` preserves the larger per-platform logs and protocol evidence.

## Issue #11 completion review

Review date: November 3, 2026. **Issue #11 is completed in release 11.7.18002.** All four original acceptance criteria and the requested publication condition are fulfilled:

| Original acceptance criterion | Result and retained evidence |
| --- | --- |
| Debug a minimal file-based app using a distributed extension, without adding a project file | Passed with the unchanged CI-built Windows ARM64 VSIX installed normally in an isolated editor. The [installation provenance](file-based-apps-2026-11-03/release-evidence/editor/provenance.json) and [public readback](file-based-apps-2026-11-03/release-evidence/readback-summary.json) identify the same package hash; the [editor result](file-based-apps-2026-11-03/release-evidence/editor/editor-result.json) records the standalone source launch. |
| Hit breakpoints, step, and inspect local variables | Passed in that installed editor: source breakpoint at line 2, local `answer=40`, evaluation result `42`, Step Over to `answer=42`, expected output, and exit 0. See the [editor result](file-based-apps-2026-11-03/release-evidence/editor/editor-result.json) and [DAP trace](file-based-apps-2026-11-03/release-evidence/editor/editor.dap.jsonl). |
| Document setup and a reproducible example | The [user guide](../file-based-apps.md) documents SDK 10.0.100+, native architecture, the four routing conditions, a three-line breakpoint example, selected-project behavior, and limitations. The [initial explicit-configuration example](2026-11-03-file-based-app-debugging.md#reproducible-editor-configuration) is also retained. |
| Preserve existing project-based debugging | The installed-release editor test also passed the existing selected-project launch, breakpoint, output, and exit checks. All eight native and eight extracted-VSIX targets passed their .NET 8/10 debugger checks in the successful [29-job release run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41587850063); the [job summary](file-based-apps-2026-11-03/release-evidence/run-summary.json) is retained. |

The GitHub release is finalized, Open VSX publication verified all eight package hashes, and the independent public readback confirmed all eight platform-specific latest feeds. A fresh completion-review read of those feeds also returned `11.7.18002` for every target.

The installed-editor evidence covers Windows ARM64 and invokes the registered F5 command after checking its binding; it does not synthesize a physical keypress or establish an eight-platform FBA editor matrix. The nonfatal post-termination transport diagnostic remains recorded above. Broader FBA fixtures across every native/extracted target are future coverage work; they do not leave any of the original four acceptance criteria unmet.

This completion update changes repository documentation only. It does not alter the release recipe or require another VSIX publication.
