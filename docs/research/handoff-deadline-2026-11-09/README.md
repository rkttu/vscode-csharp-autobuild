# Owned file-app editor handoff API deadline

Starting netcoredbg now has a separate default five-minute deadline for the owned file-app editor API admission/wait. It uses the existing monotonic clock/scheduler and an injected handoffTimeoutMs option. Checkpoints run before dispatch, at the actual queued API call and after normal true/false responses, so a delayed timer callback does not hide elapsed time. An API rejection preserves its original error unless an actual timer or abort already selected another outcome; elapsed time alone does not convert every rejection into timeout.

A timeout returns false and reports once while the original editor request stays observed. After the foreground workflow drains, the same file can start a distinct coalesced retry with fresh output even if the old API remains pending. This is an explicit exception to the general held-save source gate. A late exact owned session is stopped, without targeting the new retry or unrelated sessions.

Output cleanup still requires terminal proof. Exact owned-session termination can authorize output cleanup before the old API promise settles; pendingStarts and disposal still retain that API until actual settlement. Foreign launch arguments are prepared and checked before ownership transfer so a preparation error cannot strand owned output.

The timer excludes save, Web/certificate interaction and selected-project delegation. It disarms after accepted API response; true acceptance followed by a missing session-start event remains outside this API-wait bound. Deadline callbacks require a responsive event loop. OS requests, session-event arrival and actual drain/disposal have no hard bound or eventual-settlement guarantee.

## Source and frozen verification

Implementation commit 0e6f5394a7cfb7b4b599d47d2715bb56922da95c is over base e0c9a1058b62243e8e4e48bdf537205bb09df490. Only runtime.cjs and test-runtime.cjs change under scripts/variant. Web, unrelated product modules and the shared native lifecycle harness remain baseline-equal; the generic runProcess source is separately checked equal modulo checkout line endings.

The same implementation updates docs/file-based-apps.md. Its current bytes are separately bound to implementation Git content outside the frozen 53 variant-source archive; no pre-run/post-run documentation archive is claimed.

Frozen verification passes **291/291** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, without failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. Complete strict argv, actual executable/log/result hashes, aware timestamps, implementation-commit equality and the exact two changed variant paths are checked.

## Selected contrast and controlled witnesses

The contrast preserves seven source copies but runs only test-runtime.cjs with the selected prefix. Only baseline runtime.cjs is replaced with the exact base Git blob; all other copied bytes are identical, and current Web is verified base-equal. Exact names/counts exclude a no-match whole-file PASS. It retains **eleven intended ERR_ASSERTION baseline failures and one safe PASS**, then **all twelve pass** with the changed implementation, with zero skips/cancellations/todo.

Four baseline cases fail at the bounded foreground-result assertion rather than a missing-timer guard. The other failures retain normal-response, timer-bookkeeping, queued-dispatch and terminal-output witness payloads. The safe control preserves exclusion of save, Web interaction and already dispatched selected-project debugging. Complete scalar/multiline failure payloads and exact test names remain pinned.

The twelve cases exercise timeout and distinct retry, captured-session Stop/termination versus pending API settlement, late decline/rejection, delayed true/false responses without a delivered timer, accepted-response disarming and original rejection priority, first-winner cancellation/timeout, actual queued dispatch checks, disposal ownership, excluded phases and foreign argument preparation with corrected retry. These use controlled editor/provider APIs, clocks, scheduler callbacks and temporary filesystem outputs. They do not measure native handoff timeout or cancellation latency, OS preemption or physical UI behavior. Internal state/log values are consumed by source-bound assertions rather than separately archived raw event records.

## Retained development history and later observation

Three formal attempts retain original result/log/seven-source snapshots, exact runtime-only argv, pinned Node bytes, aware timestamps and within-attempt source-stability records:

| Attempt | Result | Source coverage |
| --- | --- | --- |
| initial-current-selected | 12/12 PASS | Historical fake-clock test helper; product runtime matches final |
| initial-current-runtime | 171 total, 164 PASS, 7 FAIL | Exact final source |
| second-current-runtime | 171/171 PASS | Identical exact final source |

After the first selected pass, the fake-clock fixture was refined to run active due timers and treat no timer as a no-op, so baseline outcome checks are meaningful. Both full runtime attempts then used the same runtime/test bytes. The initial seven failures are retained: four strict probe spawnSync ETIMEDOUT guard failures and three cleanup-readiness assertions. No cause is established; the later pass does not erase the first failure set. Current-source coverage is distinct from passing validation.

Node rendered duplicate error/stack diagnostic keys for the four asserted spawn errors. The collector binds every rendered error occurrence and the complete normalized diagnostic by hash to the original raw log, preserving exact names and short payloads. It does not collapse the record into a single YAML scalar. Development orchestration was inline without an archived runner program; completeness of all discovery/development/tool history is not claimed.

One independent **post-development** observation is retained in diagnostics/responsiveness-01.json with its original helper. The pinned Node ready process took **97.3008 ms**, and reading/hashing the current test source took **1.1431 ms**. Exact helper/Node/source/argv/result/UTC records are bound, and ordering is verified after both full development attempts. This later observation neither reconstructs their earlier conditions nor diagnoses the seven failures. It is not a product test, benchmark or native handoff-latency qualification. Collection reads the helper and record without executing the helper.

## One ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **40,567.4931 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is ordinary regression behavior, not a benchmark. It injects no delayed editor acceptance, handoff deadline or UI cancellation and does not enter certificate UI/trust.

Candidate SHA-256 is afb026a710c23e1c801d34aeaf724546bf7b57ed7b66abbaba988d7f4a4f8721; content build ID is c17dfd2e3d251938b61f02a11b6fed77c0fb55dce10ad14731b4088ae6027309. Current/Git/archive/installed modules, actual installedDependency schema, exact local-candidate metadata, the release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes are checked. The owned recovery.cjs file is the only added archive entry.

The copied launcher adds only the exact 18-byte --log trace insertion. Original/modified launcher and expectation bytes, the exact diff, frozen helper, input/prepare argv, source maps unchanged during preparation and all three trace-implementation bindings are checked. Preparation maps mean unchanged during preparation; merged-base comparisons are verified separately. The receipt's editorNotRun control describes preparation time before the later native run. Historical collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). The ordinary pass does not supersede the earlier B pause or failed compiler observation. No actual native deadline/cancellation injection, missing-session-event bound, hard OS/event-loop or whole-phase bound, bounded actual drain/disposal, physical F5/menu, macOS, calibrated total-phase budget, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **128,234 bytes**, SHA-256 9c8c78c4a209548b8b4bc344c7cec4fbed8cfa9b941f3023219803a8cc039064. It binds frozen suites, twelve-case contrast, all three development snapshots, the later contextual observation and one ordinary installed HTTP control. The collector reads retained evidence without rerunning tests or launching an editor.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/handoff-deadline-2026-11-09/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/handoff-deadline-2026-11-09/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/handoff-deadline-2026-11-09/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/handoff-deadline-2026-11-09/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/handoff-deadline-2026-11-09/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
