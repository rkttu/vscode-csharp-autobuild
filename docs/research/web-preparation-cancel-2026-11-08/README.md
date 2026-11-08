# Cooperative cancellation during Web preparation

The existing launch AbortSignal is forwarded to both UTF-8 profile reads. An already created certificate-prompt promise remains observed before a reentrant cancellation check can leave the operation, so its late rejection is handled and cannot start later certificate trust.

[Node.js v24 readFile documentation](https://nodejs.org/docs/latest-v24.x/api/fs.html#fspromisesreadfilepath-options) supports AbortSignal cancellation. It affects internal buffering rather than interrupting individual operating-system requests. This cooperative boundary does not establish finite filesystem completion or a hard whole-phase deadline. The documentation was checked on 2026-11-08, when the v24 page identified version 24.22.2.

## Source and verification

The implementation commit is 2c0f8d685e6b173473d3959492cfecb78ab78040 over merged PR #48 base 6aaad2c4e3a978b1b7e5600261ac8503f1f6a975. Only web.cjs changes among the five product modules; test-web.cjs and test-runtime.cjs supply the controls. Runtime, the shared lifecycle harness and all other variant sources match the merged base modulo checkout line endings.

Final frozen verification passes **249/249** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, with no failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. The collector checks complete strict argv, actual executable/log/result hashes, aware timestamps, exact current/archive sources, implementation-commit source equality and unchanged other sources.

The selected contrast has **three passing baseline safe controls and four intended assertion failures**, followed by **seven current passes**, with no skipped/cancelled/todo cases. It uses seven identical module/test copies and two explicit test paths; only baseline web.cjs is replaced with the exact merged-base Git blob. Complete scalar/multiline failure payloads and all test names remain pinned.

The four failing baseline witnesses are coalesced runtime progress during cooperative profile-read cancellation, the UTF-8 read-options/signal shape and immediate/late certificate-prompt rejection observed in strict child Node processes. The three passing controls preserve unanswered-modal cancellation/listener cleanup, thenable cancellation and uncancelled rejection behavior with and without a signal. Listener removal is explicit/idempotent; the original listener already used once:true, so no newly demonstrated memory-leak fix is claimed.

## One ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **26,808.5009 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed.

Candidate SHA-256 is 4b40cd489d7fdd4864307b3c316b2e763dd6b936c1a1cdc645e225b2a8b6626f; content build ID is 1cae64da9264a76ccea525b0b03f184fe5a7e0d9b19e898a817d8e1a6716e3ab. The collector binds current/Git/archive/installed product modules, the actual installedDependency schema, exact local-candidate metadata, the pinned release-base archive union only the seven allowed owned/metadata paths, all 736 unchanged non-owned payload entries and actual native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry.

A copied launcher adds only the exact 18-byte --log trace insertion. Original/modified launcher and expectation bytes, the exact diff, frozen helper, input/prepare argv, unchanged source maps during preparation and all three trace-implementation bindings are checked. Preparation source equality means unchanged bytes during preparation of this implementation commit; the Web module differs from the merged base while runtime remains unchanged. The receipt's editorNotRun control describes preparation time before the later single native attempt. Historical collectors remain unchanged.

The corrected retry's bound UTF-16-offset log slice orders build completion, Preparing web launch settings, selection of the adjacent a.run.json LifecycleHttp profile, Web preparation completion and handoff. Its captured HTTP response matches the corrected launch's exact PID and nonce. The controlled slice contains no dev-certs command. This establishes ordinary HTTP profile/read/launch regression evidence, not native AbortSignal inspection, held filesystem cancellation, certificate UI/trust or a hard deadline. Cancellation and late prompt rejection witnesses belong to the identified dependency-injected strict unit controls. Resource/phase timestamps are discrete observations, not completion bounds.

## Retained development records

The two first retained development runs pass: seven selected controls and a combined Web/runtime focus of 161 cases (25 Web, 136 runtime). Each original result/log has seven exact module/test source copies, pinned Node bytes, exact strict TAP argv, aware timestamps and source-unchanged confirmation. The collector checks those archives against current source. Earlier read-only discovery probes were reported without raw archives and are not final validation; completeness of all development/tool history is not claimed.

## Remaining scope

Runtime behavior, save/cleanup ownership and unresolved/captured editor sessions remain unchanged. Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open. A new ordinary-flow pass does not supersede the earlier B pause or failed compiler observation. No physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **115,179 bytes**, SHA-256 620b4bca35211e389f66837ef787ffaedf9105850fadc8052f941ccb7942f82d. It binds the final frozen suites, source-bound contrast, the two retained source-archived development attempts and the single ordinary installed HTTP control. The collector does not rerun suites or launch an editor.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/web-preparation-cancel-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/web-preparation-cancel-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/web-preparation-cancel-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/web-preparation-cancel-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/web-preparation-cancel-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
