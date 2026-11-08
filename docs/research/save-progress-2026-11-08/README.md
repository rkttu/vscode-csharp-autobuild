# Saving inside the file-command progress operation

Saving a dirty C# file is now included in the command's single cancellable progress operation. The command observes actual save settlement and retains same-file coalescing and disposal ownership until that settlement. Cancel during save prevents later SDK work after save settles. The preparation timer starts after actual save settlement; the total operation clock includes save.

The official [TextDocument.save API](https://code.visualstudio.com/api/references/vscode-api#TextDocument) returns Thenable<boolean> and accepts no CancellationToken. A progress cancel request cannot preempt the save operation. No finite save duration, hard save deadline or total-phase deadline is claimed.

## Source and verification

The implementation commit is bb5d03624d01c4e89331d24cc832e68d5691b061 over merged PR #47 base 9cf30ef64ba53aea3dd153d802b43ec2d7068d01. Only runtime.cjs and test-runtime.cjs change under scripts/variant. All other variant sources, including the shared lifecycle harness, match the merged base modulo checkout line endings.

Final frozen records pass **243/243** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, with no failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. The standalone collector checks complete strict argv, actual runtime/log/result hashes, aware timestamps, implementation-commit source equality and unchanged other sources.

The selected contrast uses identical changed tests and other module copies against the exact merged-base Git runtime and changed runtime: **six intended assertion failures before, six passes after**, with no skipped/cancelled/todo cases. Exact test names and complete multiline TAP assertion/error diffs remain pinned. The six controls cover held-save cancellation and coalesced corrected retry, quiet late save rejection, cancellation from the save-phase report before dispatch, an already requested token, save time excluded from preparation while included in total phase duration, and another file progressing while the original captured document remains owned.

## One installed ordinary-flow smoke

One fresh normally installed Windows ARM64 VSCodium compiler-failure/dirty-retry smoke passed in **38,644.0617 ms** of scenario time, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. One actual CS0103 attempt saved broken source, returned false and started no session. Three concurrent corrected callers shared one fresh build/session; B preservation and final exact output/queue cleanup were observed.

Candidate SHA-256 is 4697204ff12578e27bf8f7bb90df81c1d742660bde9674fd9f566db37d662bc3; content build ID is 8b1cf3523401c88f6fbb6eb20b1ac9f6a729836d74f65e4d84e131fabdafcb6e. The collector binds the actual installedDependency schema, current/Git/archive/installed product modules, exact local-candidate metadata, the pinned release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry.

A copied launcher adds only the exact 18-byte --log trace argument insertion to shared run.ps1. Original/modified launcher and expectation bytes, the exact diff, frozen helper, exact input/prepare argv, unchanged source maps during preparation and all three trace-implementation bindings are checked. Preparation source equality describes unchanged bytes during preparation of this implementation commit; runtime differs from the merged base. The receipt's editorNotRun control describes preparation time before the later single native attempt. Historical collectors remain unchanged.

Both the failed-build and corrected three-caller retry log slices retain exactly one Saving C# file start/completion before SDK/build. The collector validates the original UTF-16 log offsets and hashes, the failed attempt's actual sourceSaved flag and the unchanged harness's exact dirty-correction check. The reported save-phase lines show 114 ms and 62 ms respectively; these are ordinary observations. A separate retry save flag was not serialized or invented.

This native control establishes ordinary save-phase visibility. It does not exercise native save cancellation, a held/non-cooperative save provider or a hard deadline. Those cancellation/settlement boundaries are assessed by explicitly identified dependency-injected unit controls. Resource timestamps are discrete observations, not actual deletion timing or a latency bound.

## Retained development attempts

The first selected development run passes all six cases. An initial full focused attempt was interrupted after the test harness left its corrected retry waiting on the old copied save provider: changing options.save did not update preparationFixture's spread copy. Its original result/log and six source copies remain intact. The actual Node footer reports 75 cases, 74 passes and one file-worker failure after the reported owned-worker termination; this is incomplete coverage of the expected 135 cases. A stable mutable provider delegate corrected the test fixture, and a separately named corrected focused run passes all 135 cases with its own six source copies. Product runtime bytes are unchanged across these three retained attempts.

The two setup failures before Node launch and the process-identification/termination account are separately retained operator transcriptions. They are not raw process logs or additional completed test runs. The collector checks actual argv, source archives, hashes, results, reported counts and aware timestamps without inferring complete development history.

## Remaining scope

Existing unresolved/captured editor-owned sessions and terminal cleanup drain retain their conservative ownership until real evidence and actual settlement. Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open. A new ordinary-flow pass does not supersede the earlier unexplained B pause or failed compiler observation. No physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, publication or release qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **121,435 bytes**, SHA-256 9948e1a6da6fdbd04daeb4d679fa3b1e9de1422c8ce07a23b4bcec97d7eaf9fe. It binds the final current-source frozen suites, selected source-bound contrast, actual development attempts and the single ordinary installed smoke. No suites or editor sessions are rerun by the collector.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/save-progress-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-progress-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-progress-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-progress-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-progress-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
