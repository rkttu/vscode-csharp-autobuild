# F5 retry reliability release

Date: November 3, 2026. Distribution: `dotnetdev-kr-custom.csharp-with-netcoredbg`. The [active-file guide](../file-based-apps.md#retrying-after-a-build-error) describes the affected version and temporary workaround.

## Problem and change

In `11.7.18002`, a failed file-based build displays an error notification and waits for its dismissal. That wait also delays failed-output cleanup and removal of the file's pending operation. Editing the source and pressing F5 again returns the previous operation, so the corrected file is not saved or rebuilt until the notification closes. A save exception has the same failure path.

The fix displays the error without awaiting notification dismissal. The failed operation can finish cleanup and release the file for the next F5. Notification delivery failures are logged without blocking that release. Builds still report errors and do not launch a failed output, and repeated F5 during an actual build still shares the in-progress operation. This change adds no upstream source edits and retains the existing adapter, project routing, and SDK requirements.

## Verification

The independent [original-runtime reproduction](file-based-apps-2026-11-03/retry-evidence/notification-pending-repro.json) records one failed build, a corrected source whose second F5 cannot build while the notification remains open, and recovery only after notification dismissal.

Regression tests keep the notification promise unresolved and verify that build and save failures finish, failed build output is removed, and a subsequent F5 saves and launches the corrected source. They also cover asynchronous and synchronous notification delivery failures. The final local checks passed 31 Node tests and 33 variant Python tests. The two retry regressions failed against the original runtime before the fix.

The unchanged CI-built `11.7.18003` Windows ARM64 VSIX was installed normally into an isolated VS Code 1.144.1 profile and passed ten [real-editor assertions](file-based-apps-2026-11-03/retry-evidence/editor/README.md). An actual missing-using `CS0246` build failure returned `false` in 2.461 seconds. Read-only observations of that test editor's renderer confirmed the error notification was still visible after failure and after the repaired source's retry started; no notification-dismiss command was issued. The retry hit its breakpoint, inspected local `40`, evaluated/stepped to `42`, produced the expected output, and exited normally. Same-file Web SDK conversion and the existing selected-project regression also passed.

The tested VSIX SHA-256 is `15ce16bab7305f11fc40b18c8738ee9226d2fb4acb6301e49f702ae8f3dcb39f`, matching the package-job verification record. Installed files match the archive, and all three owned modules match canonical Git bytes at `1d5f543`. The runtime module has SHA-256 `5f1692df304538ded82e2945afc24ae193d4f19d92034e560bdcb473c3cddf4d`. The retained upstream compiled entry still has SHA-256 `b9b22a4523458d4f5e8763e87f84b4cc3c3a60be0321a01fef10c0cb445aecea`.

This editor evidence covers Windows ARM64, SDK 10.0.402/runtime 10.0.13, the contributed F5 binding, and the actual registered command. It does not synthesize a physical keypress or test Cursor. Two post-session transport read diagnostics remain recorded; all three debug sessions and the editor host exited normally. This release does not claim to resolve those diagnostics.

## Publication

The release retains C# `v11.7.18-prerelease` at `1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at `9744e1f051866215611b8440c638042aa2aa2f72`. The fix was pushed as [`bdd41ed5985c90494af39dc412b10df406c171fc`](https://github.com/rkttu/vscode-csharp-autobuild/commit/bdd41ed5985c90494af39dc412b10df406c171fc), followed by the investigation-scope documentation.

[Release run 41602853096](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41602853096) used source commit `1d5f543dc86fa5aba6da0c8c2c2f94c2668836c7` and selected **11.7.18003**, packaging revision 3, tag `csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r3`. Its fingerprint is `de497678aeb0d9c9202c76d224fea3df9ad4807465fde70579634a35c70f555a`, with recipe `48cab21d8e111c72a4b2f8e38b542d1634505249334a0139b62893b25617d5f7`. All 29 jobs completed successfully: eight native source/DAP targets, eight packages, eight extracted-VSIX targets, and the associated orchestration and publication jobs. Both .NET 8 and .NET 10 and the required upstream scenarios passed in every native/extracted target. The [job summary](file-based-apps-2026-11-03/retry-evidence/run-summary.json) preserves the individual conclusions and URLs.

Version **11.7.18003** is published on [Open VSX](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg) and in the [GitHub release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r3). GitHub finalization occurred on November 3, 2026 at **18:17 KST**. The publisher downloaded and hash-verified all eight public VSIX files before finalizing the release.

Independent public readback confirmed all eight exact-version records and all eight platform-specific latest feeds at `11.7.18003`. It downloaded the public Windows ARM64 VSIX, matched its whole-file hash to both the release manifest and the installed-editor test, compared all three owned modules to canonical Git bytes, and matched all 16 debugger payload files to the validation manifest. The [release evidence](file-based-apps-2026-11-03/retry-evidence/README.md) preserves those manifests, publication status, and readback results. The separate eight-platform debugger matrix does not establish eight-platform editor UI coverage.

The intermittent Web SDK resource-glob investigation is separate; this release does not claim to fix its unconfirmed cause.

## SDK directive transition follow-up

The user reported that adding `#:sdk Microsoft.NET.Sdk.Web` during editing triggers a delayed project-context transition: IntelliSense eventually recovers, while F5 then appears unresponsive. Restarting Cursor restores command execution but can still lead to a long build. The subsequent log confirms an actual F5 `dotnet build` invocation ending in `MSB3552` for the literal `**/*.resx` pattern. That build failure can then enter the notification-wait bug fixed above. The editor transition itself has not been established as a command-registration failure.

An isolated same-file CLI evaluation with SDK `11.0.100-rc.2.26504.105` reflected the saved SDK directive and then `PublishAot=false` in separate processes immediately; both follow-up evaluations completed in under 500 ms. The [query results](file-based-apps-2026-11-03/retry-evidence/sdk-query-results.json) establish that narrow observation. They do not reproduce the user's SDK RC1 full build, home-directory resource glob, or Cursor language-service transition.

The F5 build explicitly passes `-p:PublishAot=false` for managed debugging. This release does not change how the upstream language service refreshes SDK/property directives, disable Web SDK default content, or claim to resolve the resource-glob exception.

A separate [installed-baseline editor test](file-based-apps-2026-11-03/retry-evidence/sdk-switch-only/README.md) edited an already-open plain file into a Web SDK app before its first F5. In VS Code 1.144.1 on Windows ARM64 with SDK 10.0.402, a transient `CS0103` appeared after about one second, WebApplication hover recovered after about two seconds, and diagnostics cleared after 3.52 seconds. The registered F5 command then started the Web SDK build and reached a source breakpoint. This unchanged `11.7.18002` package test did not reproduce the reported failure. It does not cover Cursor, physical F5 routing, SDK 11 RC1, the user's home tree, or the complete user-supplied HTTP/PInvoke application.
