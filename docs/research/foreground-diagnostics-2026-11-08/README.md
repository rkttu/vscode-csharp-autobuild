# Foreground diagnostic failure containment

Runtime command and classification log writes now use the existing best-effort phase logger. A checkpoint immediately after command logging prevents reentrant cancellation or disposal from dispatching a provider that ignores its signal. Four Web diagnostic writes use a private safe logger: profile precedence, selected profile, virtual profile and certificate-attention messages.

These changes keep diagnostic-sink exceptions from replacing business behavior. Original build/profile/certificate errors, consent choices and progress callback failures remain observable. Progress callbacks are not swallowed, and child/session/provider drain and output ownership are preserved.

## Source and frozen verification

The implementation commit is 677917d4b2d3f265eece193947fe1f62fca327d9. The merged PR #51 base is 4f1e0f816cc602599f1ce0fd1d97aba0dad81975. Only runtime.cjs, web.cjs and their two tests change. The generic runProcess source is checked equal to the base modulo checkout line endings. Unrelated product modules and the shared native lifecycle harness remain baseline-equal; no new process/drain protocol is introduced.

Frozen verification passes **268/268** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, without failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. The collector checks complete strict argv, actual executable/log/result hashes, aware timestamps, implementation-commit equality and the exact four allowed changed paths.

The contrast uses identical changed tests and seven source copies. Only baseline runtime.cjs and web.cjs are replaced by their exact merged-base Git blobs. It retains **six intended baseline failures and one safe PASS**, then **all seven pass** with the changed implementation, with zero skips/cancellations/todo. Four baseline failures are ERR_ASSERTION records; two are ERR_TEST_FAILURE records from propagated profile/certificate diagnostic throws. Reentrant command-log cancellation/disposal with progress-error preservation is the existing safe control. Exact names and complete scalar/multiline error payloads are pinned.

## Controlled fault witnesses

Two runtime cases inject command or classification sink failures, retain the original build failure and owned-output cleanup, then assert a dirty retry with three callers shares one save/build/session and fresh output. Another case injects reentrant cancellation/disposal during command logging and verifies no SDK provider dispatch, retained diagnostics ownership and observable progress failure. A certificate-cancellation case checks quiet cancellation/disposal during attention logging or held consent, no later trust, listener cleanup and no writes to disposed output after a late answer.

Three public Web cases compare selected and virtual HTTP launch values, preserve conventional-profile precedence and the original malformed-profile error, and preserve consent/refusal, trust/verification failure and original provider-error identity. They also check that progress failures remain visible.

These are source-bound controlled fixtures with throwing diagnostic sinks, substituted SDK/certificate/editor/debug providers and temporary filesystem outputs. They are not native SDK, certificate UI/trust or installed output-sink fault measurements. Internal fixture logs/state are consumed by assertions rather than separately archived as raw event records; retained source and TAP bind the assertions that executed.

## Retained development observation

One formal development attempt is retained: initial-current-selected **7/7 PASS**, with its original log/result, strict runtime-then-Web argv, exact seven current source copies, pinned Node bytes, aware timestamps and unchanged-source confirmation. No separate focused runtime/Web development run occurred, and the orchestration helper program was not separately archived. Final full suites and contrast provide final source-bound coverage.

Earlier read-only VM diagnostic discovery was reported in tool stdout without raw archives. It is not final validation, and completeness of all discovery/development/tool history is not claimed.

## Ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **40,609.311 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is ordinary regression behavior, not a benchmark. It does not inject native diagnostic-sink failures, exercise the new safe logger against a bad installed channel, or enter certificate UI/trust.

Candidate SHA-256 is 5ac5719b54c4568b6d4bd01f596d707a9b50d699e583c47a22ecb824511b8da0; content build ID is cd9736a06a7a2f077338e1997ef117eb45223019f424d846f91c27ed8eebd001. The collector retains strict current/Git/archive/installed module binding, actual installedDependency schema, exact local-candidate metadata, release-base archive union only the seven allowed owned/metadata paths and exact validation of all 736 unchanged non-owned payload entries plus native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry. It checks the copied launcher's exact 18-byte --log trace insertion, original/modified launcher and expectation bytes, frozen helper, input/prepare argv, source maps unchanged during preparation and all three trace implementation bindings. Preparation source equality means unchanged during preparation; merged-base comparisons are checked separately. The receipt's editorNotRun control describes preparation time before the later native run. Historical collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). An ordinary-flow pass does not supersede the earlier B pause or failed compiler observation. No actual native sink fault, certificate modal/trust/HTTPS certificate interaction, hard whole-phase deadline, physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **106,206 bytes**, SHA-256 010368057317ba544aa500d70f2c8e2b88be7d6cc562b78d15da8ee94f75741e. It binds final frozen suites, exact selected contrast, one formal source-archived development attempt and one ordinary installed HTTP control. The collector reads retained evidence without rerunning suites or launching an editor.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/foreground-diagnostics-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-diagnostics-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-diagnostics-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-diagnostics-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/foreground-diagnostics-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
