# Shared preparation deadline: local controls

The development recipe adds a five-minute cancellation deadline shared by SDK discovery, project classification, SDK validation and compilation through DLL/PDB checks. It is disarmed before Web preparation or delegation to existing project debugging. This safety policy is separate from the uncalibrated release-performance budgets in the [stability contract](../../stability-contract.md).

## Logic and direct-child checks

Six new preparation-feature tests failed against the earlier runtime. The final suite passes 80 Node tests under `--unhandled-rejections=strict` and 34 Python tests. Nine added cases cover cumulative ancestor/multi-target evaluation, cleanup after a pending build settles, fresh-budget retry, quiet user cancellation, timer disarming, phase diagnostics, logging failure, a real Node child aborted by the deadline, and native process success/exit/spawn errors. Independent review found no blocking defect.

The process wrapper waits for both the exec callback and the direct child's [`close` event](https://nodejs.org/api/child_process.html#event-close) before settling. An abort error alone is not enough to release owned output. Native tests verify that the direct child is gone when cleanup begins. This does not establish cleanup of every descendant process or Web port. A non-cooperative process or blocked filesystem operation can delay return beyond five minutes; the deadline requests cancellation rather than promising a hard wall-clock return time.

## Real .NET SDK control

The [summary](evidence-summary.json) records four successful local checks on Windows ARM64 with SDK 10.0.403/runtime 10.0.14. [The driver](control.cjs) directly loads the current runtime, uses the real classifier and actual SDK processes, and mocks the editor/debugger API. No `runDotnet` implementation is injected.

The first build receives a **test-only deadline callback and a 300001 ms clock offset** after a short delay. Its `300xxx ms` timeout/phase values are synthetic; they do not record a real five-minute wait, latency measurement or threshold qualification. The control verifies the timeout diagnostic, no debug handoff and removal of the failed run directory. The same runtime and source then retry while the earlier notification promise remains unresolved: real SDK checks/build produce DLL/PDB output, and a matching mocked termination cleans it.

The successful retry's observed build phase was 1754 ms and cumulative preparation was 2072 ms in this run. These are single-run local observations, not process-tree or installed-editor qualification. Real editor/debugger operation, physical F5, VSCodium and macOS were not exercised.

## Reproduction

Copy `control.cjs` and `summarize.cjs` to `validation-artifacts/preparation-deadline-2026-11-04/probe/` beneath a repository checkout, with the reviewed runtime checkout at the sibling `worktree/` directory. It expects SDK 10.0.403 at `C:\Program Files\dotnet`, creates its own source/global.json/NuGet.Config, and uses dedicated APPDATA, .NET CLI home and storage paths.

Run `node --unhandled-rejections=strict control.cjs` from that probe directory. It writes `result.json`; `summarize.cjs` derives the compact summary. The raw local result is not committed, but its hash and the driver/runtime hashes are retained in the summary. Hashes describe exact local file bytes, including line endings, rather than a package identity or release version. No package was published.
