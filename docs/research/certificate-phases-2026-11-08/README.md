# Certificate consent and verification phases

HTTPS certificate work now persists its subphases through runtime setPhase, so progress and phase diagnostics distinguish checking, waiting for consent, trust preparation and post-trust verification. Cancellation is rechecked after progress callbacks before prompt or trust dispatch. After successful certificate handling, the runtime restores the general Web preparation phase before later environment validation; HTTP produces no extra phase transition.

The SDK preparation timer remains disarmed during certificate interaction. Cancellation and disposal retain a noncooperative trust provider and its owned output until actual settlement. No hard certificate, OS request or total interaction deadline is claimed.

## Source and frozen verification

Implementation commit 68c3924fca8a2f6419579db2dbdd7a52441d8a97 is over merged PR #50 base d01b364cdae4e6552948de55c362303f5c97efb5. Only runtime.cjs, web.cjs and their two tests change. The generic runProcess source is checked equal to the base modulo checkout line endings. Unrelated product modules and the shared native lifecycle harness remain baseline-equal; existing child/session/drain ownership and the streaming-output guard are unchanged by this patch.

Frozen verification passes **261/261** main Node tests, **39/39** Python tests and the separate **15/15** host-loss-driver VM tests, without failed, skipped or cancelled cases. All **53 pre-run archived sources** match exact current bytes and have final post-run hash confirmation. The collector checks complete strict argv, actual executable/log/result hashes, aware timestamps, implementation-commit equality and the exact four allowed changed paths.

The selected contrast runs identical changed tests and seven source copies against both implementations. Only baseline runtime.cjs and web.cjs are replaced with their exact merged-base Git blobs. It retains **seven intended baseline assertion failures and one safe PASS**, then **all eight pass** against the changed implementation, with zero skips/cancellations/todo. The existing initial-check progress cancellation guard remains the baseline safe control. Exact test names and complete scalar/multiline error payloads are pinned.

## Controlled certificate witnesses

Four runtime cases exercise held consent and coalesced cancellation with a late answer, noncooperative trust cancellation/disposal and late failure, post-trust verification attribution, and restored general Web attribution during successful or invalid DOTNET_ROOT preparation with throwing phase diagnostics. Four public Web helper cases cancel synchronously during each certificate progress callback and assert that no later prompt/process dispatch occurs, including signal propagation and listener cleanup.

These use substituted certificate process/prompt providers, editor/debug behavior and an injected clock. Source-bound assertions distinguish 7 ms checking, 13 ms consent, 29 ms trust preparation and 11 ms verification, including 60 ms cumulative time. Separate assertions exercise held consent cancellation at fake total 607 ms and trust-provider settlement at fake 131 ms while the SDK timer stays disarmed. These are controlled timing assertions, not measured native certificate or OS durations. The retained source and TAP bind assertions that executed; internal fixture progress/log/state values are consumed by those assertions rather than separately archived as raw event records.

## Retained development observation

One formal development attempt is retained: initial-current-selected **8/8 PASS**, with its original log/result, strict runtime-then-Web argv, exact seven current source copies, pinned Node bytes, aware timestamps and unchanged-source confirmation. No separate focused runtime/Web development run occurred. Final full suites and the selected contrast provide the final source-bound coverage.

Earlier read-only provider-only discovery was reported in tool stdout without a raw archive. Its short immediate-loop guard expiry was a probe limit, not a product failure. It is not retained validation, and completeness of all discovery/development/tool history is not claimed.

## Ordinary installed HTTP control

One fresh normally installed Windows ARM64 VSCodium HTTP compiler-failure/dirty-retry control passed in **30,766.9318 ms of scenario time**, with editor exit 0, all 13 phases passing and four captured sessions (A-0, B, A-1 and A-2). The original result has no first failure and no fallback cleanup. Source breakpoint/evaluation, an actual CS0103 no-session failure, three corrected callers sharing one fresh build/session, B preservation and final exact resource cleanup were observed. This is ordinary regression behavior, not a benchmark. It does not execute actual HTTPS certificate UI, trust operations, an HTTPS certificate path or the new certificate subphases.

Candidate SHA-256 is 8a67244b207bd2865007d37603cbf9d326bd8a85987839867bbdbc9bd0b5720d; content build ID is 46eaf45903a1b9e79d2465cdc594faa2a9ef24869fee7643a4eb97267bb6c687. The collector retains strict current/Git/archive/installed module binding, actual installedDependency schema, exact local-candidate metadata, release-base archive union only the seven allowed owned/metadata paths and exact validation of all 736 unchanged non-owned payload entries plus native editor/SDK/adapter bytes. The owned recovery.cjs file is the only added archive entry. It checks the copied launcher's exact 18-byte --log trace insertion, original/modified launcher and expectation bytes, frozen helper, input/prepare argv, source maps unchanged during preparation and all three trace implementation bindings. Preparation source equality means unchanged during preparation of this implementation, whose runtime/web differ from the merged base. The receipt's editorNotRun control describes preparation time before the later native run. Historical collectors remain unchanged.

## Remaining scope

Full [#18 AC6](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remain open; release qualification remains with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). An ordinary-flow pass does not supersede the earlier B pause or failed compiler observation. No actual native certificate modal/trust/HTTPS certificate interaction, hard whole-phase deadline, physical F5/menu, macOS, calibrated total-phase bound, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed.

## Evidence and regeneration

[evidence-summary.json](evidence-summary.json) is **106,360 bytes**, SHA-256 84fdd7fc2158f4f126080ed4d0cda9b1336c709e75db26295c4128ed3f4de17c. It binds the final frozen suites, exact selected contrast, one formal source-archived development attempt and one ordinary installed HTTP control. The collector reads retained evidence without rerunning suites or launching an editor.

From this worktree, this single PowerShell command validates retained records and regenerates the summary:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/certificate-phases-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/certificate-phases-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/certificate-phases-2026-11-08/regression-contrast' --smoke 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/certificate-phases-2026-11-08/smoke' --development 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/certificate-phases-2026-11-08/development' --base-vsix 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
