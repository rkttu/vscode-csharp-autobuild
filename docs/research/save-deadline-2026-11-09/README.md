# Dirty-document save deadline

Dirty-document save now has a separate default five-minute deadline, using injected saveTimeoutMs with the existing monotonic clock and scheduler. Pre-dispatch and post-await checks on normal true/false results account for elapsed time even if the timer callback has not run. The save timer disarms immediately at normal reply. Rejection preserves its original error unless an actual timer or abort already selected another outcome; elapsed time alone does not convert every rejection into timeout.

A timeout returns false once while the real save stays observed. The source gate and disposal retain that save until actual settlement; repeated same-file commands cannot start competing saves or SDK work, while other files remain independent. A late true/false/rejection cannot resume the cancelled launch or duplicate timeout notification. On the dirty-document path, SDK preparation begins only after timely actual save success with a fresh independent SDK budget.

Save precedes classification, so the dirty save of an included-project file also receives this budget. The later SDK, owned handoff, Web/certificate and dispatched-project waits keep their existing separate policies. Clean documents bypass save. A responsive event loop is required; no hard OS-request, actual save/drain/disposal bound or eventual-settlement guarantee is implied.

## Source and frozen verification

Implementation commit 868ba9e052511eb3984d526fa77137f2286eb2db is over base 2728b76b1aa4d43d288507b20dbe6277e06d6077. Only runtime.cjs and test-runtime.cjs change under scripts/variant. Web, unrelated product modules and the shared native lifecycle harness remain baseline-equal. The generic runProcess source is separately checked unchanged modulo checkout line endings.

The implementation also updates docs/file-based-apps.md. Its current bytes are separately bound to implementation Git content outside the frozen 53 variant-source archive; no pre-run/post-run documentation archive is claimed.

Frozen verification passes **302/302** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, without failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. Exact argv, original executable identities, retained-byte matches, log/result hashes, aware timestamps and the two allowed changed variant paths are checked.

## Selected contrast and controlled witnesses

The contrast keeps seven copied source files but runs only test-runtime.cjs with the selected prefix. Only baseline runtime.cjs is replaced with its exact base Git blob. Other copied bytes are identical and current Web is verified base-equal. Exact names/counts exclude a no-match whole-file PASS. It retains **eight intended ERR_ASSERTION baseline failures and three safe PASS controls**, then **all eleven pass** with the changed implementation, with zero skips/cancellations/todo.

Four baseline cases fail at the bounded foreground-result assertion. The other failures preserve normal-result, default-budget and pre-dispatch witness payloads. Safe controls preserve the fresh SDK budget after timely save, real save/disposal retention and exclusion of clean/downstream waits. Complete scalar/multiline failure payloads and exact names are pinned.

The cases exercise held timeout with same-file suppression and independent-file/retry behavior, late false/rejection, delayed normal replies without a delivered timer, default/disarmed budget behavior, original rejection priority, first-winner cancellation/timeout, pre-save progress checks, actual disposal/reentrant rejection and downstream budget exclusions. These use controlled editor/provider APIs, clocks, timers and temporary filesystem outputs. They do not measure native five-minute timeout behavior, OS preemption or physical UI cancellation. Internal state/log values are consumed by source-bound assertions rather than separately archived raw event records.

## Retained development history

Three formal attempts preserve original result/log/seven-source snapshots, exact runtime-only argv, Node/Python input identities, execution-boundary checks and aware timestamps:

| Attempt | Result | Source coverage |
| --- | --- | --- |
| initial-current-selected | 11/11 PASS | Current product; historical test snapshot |
| initial-current-runtime | 182/182 PASS | Current product; historical test snapshot |
| review-current-runtime | 182/182 PASS | Exact final product and tests |

Product bytes never changed across these attempts. The initial two test snapshots call stale callbacks directly; the final snapshot uses optional calls so an absent baseline timer is a safe no-op in negative controls instead of a TypeError. For the current timed-save cases, those callbacks remain present and are invoked. Only the third snapshot supplies final test-source coverage. Source stability is checked within each attempt, separately from equality with final source. Development orchestration was inline without a separately archived runner program; completeness of all development/tool history is not claimed. Previous-slice failures and diagnostics are not treated as this slice's observations.

## Retained verifier inputs and replay scope

The new capture keeps only the exact Node and Python EXE byte inputs under artifactroot/verifier-inputs. Node SHA-256 is 8e55f00a0aca4c8d71ff6f68aa6285118fad18c29c0482973cc03ee5f0c2a98b; Python SHA-256 is 8fc34e1314ae172c7841832ae7c63ce3d59eb7394b3ca317d69c803f93ea5660. The 3,212-byte manifest is fixed by SHA-256 f50e9b258873048bec1a091240a83a9e379d00f29b7839ecd30f9115602d87e7, with its original capture helper and UTC record bound.

Tests still executed at the recorded original cache paths. Development, full-suite, contrast and native-preparation records compare original EXE hashes with the retained pool before and after each operation. The collector validates those records and reads the content-addressed retained copies; original execution identities and actual retained read paths are both explicit in the summary. It does not open/stat original verifier files for byte validation or require current cache contents during collection. Native editor/SDK/dependency/base/adapter/trace bindings remain strict.

The capture is write-once and hash-checked. It is **EXE-only**, not a runnable Python installation, standard library, complete Node/Python environment or operating-system snapshot. Execution was not moved to the copies, and collection does not execute them. Boundary samples are distinct from a complete execution-environment archive.

A later fresh collection of [PR54's handoff evidence](../handoff-deadline-2026-11-09/README.md) encountered changed cached verifier inputs. That historical limitation and its earlier completed acceptance remain separate; its records and collectors were not rewritten or relaxed. This slice verifies only its own recorded inputs using the new retained pool. It does not reconstruct PR54's former execution or missing Python EXE, and it does not rerun the old suites.

## One ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **26,913.9721 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is ordinary regression behavior, not a benchmark. It injects no held-save provider, save deadline or UI cancellation and does not enter certificate UI/trust.

Candidate SHA-256 is 9ced3cdf7224137ea3911bf6972e3a3586d298d6af989a6c4b96dbb60380b72a; content build ID is fc94dc9a9505e6774d24fd868e9703a59ee78c597dfc10f68779f2f765fb89bd. Current/Git/archive/installed modules, actual installedDependency schema, exact candidate metadata, release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes are checked. The owned recovery.cjs file is the only added archive entry.

The copied launcher adds only the exact 18-byte --log trace insertion. Original/modified launcher and expectation bytes, exact diff, frozen preparation helper, original prepare argv, verifier-pool boundaries and all three trace-implementation bindings are checked. Preparation source maps mean unchanged during preparation; merged-base comparisons are verified separately. The receipt's editorNotRun control describes preparation time before the later native run. Historical common native collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). The ordinary pass does not supersede the earlier B pause or failed compiler observation. No native save-timeout/cancellation injection, hard OS/event-loop or whole-phase bound, bounded actual drain/disposal, physical F5/menu, macOS, calibrated total-phase budget, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **153,090 bytes**, SHA-256 e04b998f792366e3aed555d0a53e5b8339bb0bcdbf889923f231d57ee5fcc330. It binds final suites, eleven-case contrast, three development snapshots, retained executable input/boundary records and one ordinary installed HTTP control. Collection reads retained evidence without rerunning tests, executing captured helpers or launching an editor.

From this worktree, the following PowerShell command validates retained records and regenerates the summary. The shown interpreter runs the collector only; an available compatible Python can be substituted without changing recorded historical test argv. The retained Python EXE is not a complete environment for starting the collector.

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/save-deadline-2026-11-09/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-deadline-2026-11-09/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-deadline-2026-11-09/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-deadline-2026-11-09/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/save-deadline-2026-11-09/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
