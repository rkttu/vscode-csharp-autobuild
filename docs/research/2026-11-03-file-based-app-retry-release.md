# F5 retry reliability release

Date: November 3, 2026. Distribution: `dotnetdev-kr-custom.csharp-with-netcoredbg`. The [active-file guide](../file-based-apps.md#retrying-after-a-build-error) describes the affected version and temporary workaround.

## Problem and change

In `11.7.18002`, a failed file-based build displays an error notification and waits for its dismissal. That wait also delays failed-output cleanup and removal of the file's pending operation. Editing the source and pressing F5 again returns the previous operation, so the corrected file is not saved or rebuilt until the notification closes. A save exception has the same failure path.

The fix displays the error without awaiting notification dismissal. The failed operation can finish cleanup and release the file for the next F5. Notification delivery failures are logged without blocking that release. Builds still report errors and do not launch a failed output, and repeated F5 during an actual build still shares the in-progress operation. This change adds no upstream source edits and retains the existing adapter, project routing, and SDK requirements.

## Verification

The independent [original-runtime reproduction](file-based-apps-2026-11-03/retry-evidence/notification-pending-repro.json) records one failed build, a corrected source whose second F5 cannot build while the notification remains open, and recovery only after notification dismissal.

Regression tests keep the notification promise unresolved and verify that build and save failures finish, failed build output is removed, and a subsequent F5 saves and launches the corrected source. They also cover asynchronous and synchronous notification delivery failures. The final local checks passed 31 Node tests and 33 variant Python tests. The two retry regressions failed against the original runtime before the fix.

## Publication

The requested release retains C# `v11.7.18-prerelease` at `1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at `9744e1f051866215611b8440c638042aa2aa2f72`. The workflow assigns the next unreserved packaging revision and must complete the existing eight-target native, package, and extracted-VSIX gates before publication. Publication and installed-package regression evidence will be recorded here after those checks complete.

The intermittent Web SDK resource-glob investigation is separate; this release does not claim to fix its unconfirmed cause.

## SDK directive transition follow-up

The user reported that adding `#:sdk Microsoft.NET.Sdk.Web` during editing triggers a delayed project-context transition: IntelliSense eventually recovers, while F5 then appears unresponsive. Restarting Cursor restores command execution but can still lead to a long build. The subsequent log confirms an actual F5 `dotnet build` invocation ending in `MSB3552` for the literal `**/*.resx` pattern. That build failure can then enter the notification-wait bug fixed above. The editor transition itself has not been established as a command-registration failure.

An isolated same-file CLI evaluation with SDK `11.0.100-rc.2.26504.105` reflected the saved SDK directive and then `PublishAot=false` in separate processes immediately; both follow-up evaluations completed in under 500 ms. The [query results](file-based-apps-2026-11-03/retry-evidence/sdk-query-results.json) establish that narrow observation. They do not reproduce the user's SDK RC1 full build, home-directory resource glob, or Cursor language-service transition.

The F5 build explicitly passes `-p:PublishAot=false` for managed debugging. This release does not change how the upstream language service refreshes SDK/property directives, disable Web SDK default content, or claim to resolve the resource-glob exception.
