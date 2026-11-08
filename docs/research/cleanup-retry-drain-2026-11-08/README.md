# Fresh commands while older terminal cleanup drains

A fresh C# file command previously awaited a retry of an older, already terminal output’s deletion. If that filesystem operation did not settle, the new command could remain pending before save or SDK discovery. The retry now runs as observed background work. A fresh command uses a distinct output while the old retry retains its cleanupInFlight/output ownership, diagnostics and disposal drain until real completion. Late failure remains observed and recoverable. The cleanup implementation, terminal receipt authorization and current-session cleanup are unchanged.

This is one implementation slice of [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18), not completion of its total-phase-bound criterion. [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remains unresolved. These observations use dependency-injected runtime tests with real temporary filesystem paths; they add no installed-editor or release qualification.

## Scope and verification

Only runtime.cjs and test-runtime.cjs under scripts/variant differ from the merged PR #44 base. Existing retries still select one terminal entry or a global pass, coalesce an in-flight deletion, preserve live outputs and keep original launch error/cancellation behavior. The command’s pending entry can now settle while the older deletion stays held. No timeout is inserted inside cleanup() to release its drain ownership early.

Three contrasting cases cover disposal while fresh SDK work proceeds, three coalesced dirty callers plus later commands during a held deletion, and late deletion rejection followed by recovery. They check distinct fresh outputs, one shared new save/build/session, no duplicate deletion or competing global pass, independent fresh-session cleanup, retained disposal observers and unchanged launch notifications when diagnostic delivery throws.

The retained contrast uses identical changed tests and other modules against old/new runtime implementations: **0/3 pass before, 3/3 pass after**, with strict unhandled-rejection handling. Baseline failures occur at the intended foreground-progress assertions. The collector verifies every copied source/log/argv/result, the original Git runtime blob, normalized equality with merged PR #44’s runtime, and current changed bytes modulo checkout line endings. Raw files remain in validation-artifacts/cleanup-retry-drain-2026-11-08/regression-contrast.

Final frozen verification passes: **230/230** main Node tests across five product suites, **39/39** Python tests and a separate **15/15** local host-loss-driver VM suite. All **53** archived variant source files match exact current bytes before and after verification. The standalone collector checks verification executables, exact argv, result files, complete counts with no skipped/cancelled cases, aware timestamps and final source confirmation. Historical collectors are unchanged.

[evidence-summary.json](evidence-summary.json) is **21,939 bytes**, SHA-256 2df8edc86bd7a37eb6863ae2007688c0b1edd56ebf2150253e1ad41ef37128f1. The implementation commit is 8937aabf024e961415329307a1183f09cf6105ff, over merged PR #44 base 5f6b36e916e54876f54a65aa2df7212ac4ebaf40. The summary binds exact current/archive sources, all final results and logs, the original three-case contrast and the collector itself. The frozen full-suite records remain in validation-artifacts/cleanup-retry-drain-2026-11-08/tests.

## Development observations

The source author reported an initial focused runtime run with 122 tests, 114 passes and eight failures (tool output chunk f6c9df). Those existing tests expected retry/deletion/log completion immediately after a fresh command. Adaptations wait for independently observed background completion while preserving path, error, quiet-cancellation, fairness and no-global-pass assertions. The fairness case no longer assumes which concurrent failure finishes first. A later focused run reported 122/122 passes (chunk 0787c9). Complete logs for those development runs were **not archived**; the summary labels them as reported development observations. The archived final suites and three-case contrast supply final validation.

## Remaining boundary

Current-run failure cleanup can still hold its own foreground result. Save, interactive certificate work, editor-owned handoff/session lifetime and non-cooperative SDK/filesystem waits need further explicit policies under #18 AC6. A forever-pending older retry keeps its drain/ownership alive; this patch permits fresh commands but does not promise finite filesystem completion or disposal time. Native macOS, physical F5/menu, numeric calibration, descendants, language-service readiness, repeated installed profiles, CI and publication qualification remain with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15).

## Regeneration

From this worktree, this single PowerShell command validates retained records without rerunning tests or launching an editor:

    & 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B docs/research/cleanup-retry-drain-2026-11-08/summarize.py --tests 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/cleanup-retry-drain-2026-11-08/tests' --contrast 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/cleanup-retry-drain-2026-11-08/regression-contrast' --base-commit 5f6b36e916e54876f54a65aa2df7212ac4ebaf40
