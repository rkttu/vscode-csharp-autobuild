# Guarding the native streaming diagnostic callback

The native activation runDotnet path guards output.append and chunk.toString inside its streaming diagnostic callback. A fixed best-effort diagnostic is attempted at most once per process; later chunk writes remain attempted. Buffered stdout/stderr, original process results/errors, cancellation, child close and output ownership remain observed. The generic exported runProcess callback contract and other raw appendLine behavior are unchanged.

Actual fault injection targets output.append, including a hostile thrown value and a secondary diagnostic appendLine failure. Conversion containment is covered by source inspection; a failing chunk.toString was not injected.

## Source and verification

The implementation commit is cadf6fcb327292cbc513821fe6a058ae8bb90981 over merged PR #49 base 18bf9a95fb0b043581cf3802b4db2e23a161b2d6. Only runtime.cjs and test-runtime.cjs change. Web, the shared lifecycle harness and other variant sources remain baseline-equal modulo checkout line endings. The collector separately checks that the generic runProcess function source is unchanged from the base.

Final frozen verification passes **253/253** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, with no failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. Complete strict argv, actual executable/log/result hashes, aware timestamps, implementation-commit equality and unchanged other sources are checked.

The selected contrast uses identical changed tests and six source copies; only baseline runtime.cjs is replaced by the exact merged-base Git blob. Its four parent assertions retain strict probe-host exit-1/sink-error diagnostics against the previous runtime, then **all four pass** against the changed runtime, with no skipped/cancelled/todo cases. Exact test names and complete error payloads remain pinned.

## Controlled fault witnesses

The four modes cover success, original build failure, cancellation and disposal. Strict child Node activation probes use a VM exec adapter leading to real Node CLI stand-ins and real OS children; SDK/classification/editor/debug-adapter behavior is substituted. Source-bound assertions check stdout/stderr buffering, original exit-23/error-buffer identity, continued chunk-write attempts, at-most-once reporting, pending cancellation/disposal, close-before-cleanup ownership, independent live/external preservation and exact original output identity.

These are controlled append-fault witnesses, not installed SDK/adapter output-sink fault measurements. Fatal baseline results belong to the strict standalone probe host. Installed VSCodium exception policy is not measured; an actual installed-host sink-failure crash or #45 cause is not established. Successful inner PID/close/buffer values were consumed by parent assertions and are not separately archived as raw numerical records; the retained source and TAP bind the assertions that executed.

## Retained development witness history

Four groups retain original result/log/six-source snapshots: initial selected **4/4**, initial focused runtime **140/140**, explicit synchronous-PID focused runtime **140/140** and final exact-output-identity focused runtime **140/140**. Runtime bytes never changed across these runs. The earlier three test snapshots differ from final tests and provide historical witness coverage; only the last supplies final test-source coverage.

The PID marker was changed to fs.writeSync for explicit portable witness reliability. No truncation was observed in the archived passing Windows pipe runs. [Node process I/O guidance](https://nodejs.org/docs/latest-v24.x/api/process.html#a-note-on-process-io) distinguishes synchronous Windows pipe writes from asynchronous behavior on other platform/target configurations. Cleanup observation was then bound to JSON source/originalOutput and the exact original build output, so older queued cleanup cannot be attributed to a newer same-source row.

Earlier read-only runProcess throw discovery was reported only in tool stdout without a raw archive. It is not final validation, and completeness of development/probe/tool history is not claimed. The final source-bound full suites and contrast are authoritative for this change.

## One ordinary installed HTTP regression

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **51,687.5137 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is an ordinary regression run, not a benchmark or injected native output-sink/conversion fault experiment.

Candidate SHA-256 is e7c5a29354eb46fcd4ff319225e89a2d463266944822090e337ec96ec04cf4bd; content build ID is cb793eecda0f052ab83937d01889495aac75617b88ed7f2bf65c72dd22464b3e. The collector binds current/Git/archive/installed modules, actual installedDependency schema, exact local-candidate metadata, the release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry.

The copied launcher adds only the exact 18-byte --log trace insertion. Original/modified launcher and expectation bytes, the exact diff, frozen helper, input/prepare argv, source maps unchanged during preparation and all three trace-implementation bindings are checked. Preparation source equality means unchanged during preparation of this implementation commit, whose runtime differs from the merged base. The receipt's editorNotRun control describes preparation time before the later native run. Historical collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). A new ordinary-flow pass does not supersede the earlier B pause or failed compiler observation. No hard whole-phase deadline, physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **119,524 bytes**, SHA-256 0dfa6362f7be3e3e535feb5349a9162854dee43c78c2d4003aa138568569b7a3. It binds the final frozen suites, exact selected contrast, four historical source-archived development stages and one ordinary installed HTTP control. The collector does not rerun suites or launch an editor.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/stream-output-guard-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/stream-output-guard-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/stream-output-guard-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/stream-output-guard-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/stream-output-guard-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
