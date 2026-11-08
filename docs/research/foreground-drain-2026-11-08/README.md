# Foreground cancellation and actual workflow drain

Foreground cancellation or the existing SDK preparation deadline can now return false and release the file-debugging progress task while the real save, SDK, filesystem or certificate workflow remains observed. The source gate, disposal drain and owned output stay held until actual settlement. Repeating the same-file command returns the previous result without another save/build/progress; other files can proceed independently. Late results cannot resume a cancelled launch, and late failures remain diagnostic evidence.

The first selected outcome is preserved: cancellation remains quiet, timeout reports once, and neither is replaced by a later progress-provider error. An already completed workflow also wins over later progress-provider errors. Cancellation requires a responsive event loop; it does not terminate an arbitrary provider or establish output cleanup. A provider that never settles may retain the source gate and shutdown drain indefinitely.

Dispatched selected-project debugging remains an explicit exception: its editor-owned completion is awaited because this controller has no exact project-session ownership. At an owned file-app handoff gap, cancellation targets only the launch matched to generated output and uses the existing exact-session Stop/termination path. Pending-start ownership stays conservative.

## Source and frozen verification

Implementation commit a03b247561208d0a0ec180b4980154e5f0b0451e is over base b81e78f58055d352eaa5d7f14e5c436b7b3e85b5. Only runtime.cjs and test-runtime.cjs change under scripts/variant. Web, unrelated product modules and the shared native lifecycle harness remain baseline-equal. The collector separately verifies the generic runProcess source is unchanged modulo checkout line endings.

The same implementation updates docs/file-based-apps.md. Its current bytes are separately bound to implementation Git content; it is outside the frozen 53 variant-source archive, and no pre-run/post-run documentation archive is claimed.

Frozen verification passes **279/279** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, without failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. Complete strict argv, actual executable/log/result hashes, aware timestamps, implementation-commit equality and the exact two changed variant paths are checked.

## Selected contrast and controlled witnesses

The contrast preserves seven copied source files but runs only test-runtime.cjs with the selected prefix. Only baseline runtime.cjs is replaced by the exact base Git blob; all other copied bytes are identical, and current Web is verified base-equal. Exact selected names/counts exclude a no-match whole-file PASS. It retains **eight intended baseline failures and three safe PASS controls**, then **all eleven pass** with the changed implementation, with zero skips/cancellations/todo. Seven failures are ERR_ASSERTION; the empty-error ERR_TEST_FAILURE also retains its exact abort stack.

The eleven cases cover a held save with same-source suppression and an independent file, SDK-discovery/classification timeouts, held build/trust/filesystem work and output ownership, reentrant rejected save/pre-cancel handling, progress-provider failures, completed-workflow precedence, dispatched-project completion and exact captured-session handoff cancellation. Controlled first-winner subcases retain cancellation/timeout ahead of later outer progress-provider rejection. Assertions check foreground listener/timer release, no late progress reports, actual disposal/cleanup after provider settlement and late failure observation.

Three safe controls preserve rejected-save handling, selected-project completion and exact captured-session Stop behavior. The handoff listener-count witness identifies the current controlled gap; baseline listener-count one may identify the earlier handoff listener instead. Its baseline PASS does not prove both implementations reached an identical microtask gap or reproduce an old gap defect. There is no native/UI microtask-gap measurement.

These are source-bound fixtures with substituted providers, editor/debug APIs, cancellation/timers and clocks. Filesystem cases use temporary directories with controlled promise settlement. Test waiting guards and injected phase durations are not measured native cancellation latency, OS-request preemption or hard whole-phase deadlines. Internal fixture progress/log/state values are consumed by assertions, rather than separately archived raw event records; retained source and TAP bind the assertions that executed.

## Retained development history

Four formal attempts retain original log/result/seven-source snapshots, exact strict runtime-only argv, pinned Node bytes, aware timestamps and within-attempt unchanged-source confirmation:

| Attempt | Result | Source coverage |
| --- | --- | --- |
| initial-current-selected | 10/10 PASS | Historical source before the filesystem-allocation case |
| initial-current-runtime | 159 total, 155 PASS, 4 FAIL | Historical source and old foreground/drain expectations |
| revised-current-runtime | 159/159 PASS | Historical runtime after test-witness adaptation |
| review-corrected-current-runtime | 159/159 PASS | Exact final runtime and tests |

The four initial full-runtime failures remain verbatim: stream-child cancel/dispose expected command return to imply child close, a coalesced-build test expected callers to remain pending, and a certificate cancellation test expected the previous listener count. Updated witnesses keep the actual close, output ownership and disposal assertions while separating foreground results from real drain.

Review then found a concrete first-winner bug: a later outer progress-provider rejection could replace an already selected cancellation/timeout while work remained held. The runtime fix and expanded existing selected case precede the fourth run. The first three snapshots have historical runtime/test bytes and do not supply final-source coverage. currentSourceUnchanged means unchanged within each attempt, not equality with final source. No separate development orchestration program is archived, and completeness of all discovery/development/tool history is not claimed.

## One ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **43,345.0564 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is ordinary regression behavior, not a benchmark. It does not inject native cancellation, held providers, SDK deadlines or certificate UI/trust.

Candidate SHA-256 is 27024230783657c6b8a1885aa99e263f4c3688212dea627c4ab8095b62590040; content build ID is b59e11c644461dddfbf3fd828f3f6459e2b992c1cff63e120e4ce364b336093d. The collector binds current/Git/archive/installed modules, actual installedDependency schema, exact local-candidate metadata, the release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry.

The copied launcher adds only the exact 18-byte --log trace insertion. Original/modified launcher and expectation bytes, the exact diff, frozen helper, input/prepare argv, source maps unchanged during preparation and all three trace-implementation bindings are checked. Preparation maps mean unchanged during preparation; merged-base comparisons are verified separately. The receipt's editorNotRun control describes preparation time before the later native run. Historical collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). An ordinary-flow pass does not supersede the earlier B pause or failed compiler observation. No actual native held-provider cancellation/deadline or certificate modal/trust interaction, bounded actual drain/disposal, hard OS-request or whole-phase deadline, physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **124,389 bytes**, SHA-256 4fbdc3ac5d8397773574b54d5b00a88693923d7b3e14eacc2169b5eb96d8569f. It binds final frozen suites, the eleven-case selected contrast, four historical/final development snapshots and one ordinary installed HTTP control. The collector reads retained records without rerunning suites or launching an editor.

From this worktree, this single PowerShell command validates retained evidence and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/foreground-drain-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-drain-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-drain-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-drain-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-drain-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
