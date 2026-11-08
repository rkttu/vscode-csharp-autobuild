# Abrupt active extension-host loss and conservative retry

The primary installed control `n01` **passes**: one verified extension-host instance is force-killed while a real native Web app is running; the same isolated editor starts a replacement host, the old native processes/port release, unknown original output remains intact, and a dirty public-command retry starts and cleans a fresh output. The separate compiler regression `c01` **fails** after B is paused and its HTTP probe times out. This evidence change has no product-module changes and does not qualify a release or close [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18).

Both controls use an unreleased local candidate over merged [PR #43](https://github.com/rkttu/vscode-csharp-autobuild/pull/43), source `32eae02d4c9594be42d85f93fa1e38b079184867`: native Windows ARM64 VSCodium `1.143.17232` / API `1.143.1`, SDK `10.0.403`, runtime `10.0.14`, and base package `11.7.18004`. All five owned product modules retain their merged bytes. Candidate, dependency, editor, SDK, archive payload, installed module and harness hashes are bound by [summarize.py](summarize.py).

## Primary observation

The new local test driver is separately packaged and normally installed by the isolated CLI alongside the candidate and runtime dependency. It activates through `onStartupFinished`; both actual hosts report `ExtensionMode.Production` (`1`). There are no `--extensionDevelopmentPath` or `--extensionTestsPath` arguments. “Production mode” describes this isolated editor extension mode, not a deployed production environment.

| Observation | Retained identity/result |
| --- | --- |
| One normally launched editor | Main PID `97568`; one app launch; exit `0` |
| Old extension host → automatic replacement | `7724` → `101472`, both verified through process lineage to the same main editor and profile |
| Native app before fault | Adapter `100536` → debuggee `33244`; owned HTTP nonce/revision and DAP local-process PID agree; port `51232` occupied |
| Fault | Only the retained exact old extension-host handle receives `Kill()`; repeated CIM PID/path/command/creation/parent checks and exact phase/readiness hashes precede the action |
| First post-kill external sample | Retained old host/adapter/debuggee handles report exited; HTTP fails and port binds; original output/program/guard files remain |
| Replacement recovery | Exact initial new-log slice says `scanned=0, attempted=0, removed=0`; old unknown active output is preserved |
| Dirty corrected retry | Three `true` callers, one actual quoted SDK build, one fresh session/token/output; owned HTTP PID `85960`; normal exact-session Stop, termination/PID/port/output cleanup |

Before the fault, the driver saves a successful native launch/checkpoint, original DLL/PDB proofs, a nonce sentinel in its output and a nonce guard in an unrelated unmarked sibling `run-*` directory. The external launcher acquires retained OS handles for the exact host, adapter and app; only the extension host is killed. It does not call test Stop, Reload or deactivation for that old session. The complete first-host trace retains later harmless thread/output messages after the immutable checkpoint, without a recorded terminate/disconnect request before host loss. The killed host cannot provide a post-death transcript.

The kill request is recorded at `2026-11-08T08:25:10.5177570Z`, exit observation at `08:25:10.5499266Z`, and the first post-kill sample starts at `08:25:10.5525772Z`. Further samples include actual UTC times `08:25:12.8323861Z`, `08:25:15.6103287Z`, `08:25:18.3504418Z` and `08:25:23.0435994Z`. Labels `after-250ms` and `after-1000ms` describe inserted delays after earlier sequential probes; HTTP probes can themselves consume two seconds. Each sample also contains sequential checks. These are discrete, non-atomic observations, not calibrated cleanup-latency bounds.

The driver records `candidateAlreadyActiveBeforeExplicitActivation=true`. Its immediate old-resource snapshot is before its explicit `activate()` call, and may follow automatic candidate activation/background recovery. The initial replacement log is a historical 60-byte slice (SHA-256 `2c243cf08ad6fc1d7c8eeee7d8c8304452bce39327882883f1ebbe7aff992278`); the collector checks that prefix/tail against the later enlarged current log and binds the whole file separately. It does not treat a later old-host log flush as replacement recovery.

Old DLL/PDB, sentinel and unmarked guard bytes remain exact through final editor exit, with empty terminal queues. Those unknown paths have no terminal-cleanup authorization merely because the host, adapter or app exited. Their preservation follows conservative ownership policy. The new retry uses a distinct output/session/token; exact test Stop is requested at `08:25:22.293Z` and its released resources are observed at `08:25:22.848Z`. Fresh retry cleanup does not delete the old unknown output. This primary has one initial app and one retry, no independent B, no active-build interruption, and no breakpoint/stepping check.

## Original compiler regression failure

The ordinary `build-failure-retry` control `c01` retains its first failed result and editor exit `1`; no automatic resume or rerun replaces it. Initial A/B native launches, A breakpoint/evaluation, targeted A Stop/cleanup, B preservation, and the deliberate `CS0103` failure/no-session/owned cleanup complete. Corrected A then saves and produces three `true` callers, one real SDK build, one session, and HTTP-ready PID `98816` at `17597.1278 ms`.

B's exact session receives an editor-to-adapter `pause` request (`seq=10`) at `14263.0925 ms`, a `stopped` event with reason `pause` at `14275.5813 ms`, and its successful correlated response. There is no B `continue` between that pause and the first failure at `19604.7847 ms`: `TimeoutError: The operation was aborted due to timeout`. The stopped interval explains why the later HTTP check cannot demonstrate B remains responsive. The higher-level pause caller/trigger is **unproven**; this evidence does not identify user input, Hot Reload or a product component as its origin.

Subsequent exact-session Stop and PID-exit observations are failure safety. Launcher fixture HTTP-shutdown attempts time out. Current sampled A-0 output is absent, while B and A-1 output directories remain; their file hashes are retained. None of that is relabelled as successful B preservation, all output cleanup, or three completed retry cycles. The collector validates the failed observation separately and leaves the historical passing compiler collector's assertions unchanged. Full `trace.jsonl`, original result, launcher result and C#/extension-host/renderer/output logs are bound for investigation.

## Acceptance and retained evidence

[acceptance-audit.md](acceptance-audit.md) maps all seven original #18 criteria to code, unit and installed evidence, separating [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15) qualification. The original total-phase/indefinitely unsettled machine-I/O boundary remains open under criterion six. Host loss does not settle that design issue. A small proposed next implementation slice is observing known-terminal cleanup retry in the background while retaining real drain/output ownership until actual settlement; never-settling/late-resolving/rejecting cases require explicit tests and policy. The failed compiler regression also remains an acceptance blocker for this evidence change.

Raw inputs remain under `validation-artifacts/host-loss-2026-11-08/{n01,c01,tests}`. The unit manifest archives all **52** tracked or new unignored `scripts/variant` source byte copies, checks exact pre/post hashes and the full current source set, and retains exact argv, verification-runtime hashes, logs and results: **228 Node tests / 39 Python tests pass**. Those unit results do not override `c01`'s failed installed observation.

[evidence-summary.json](evidence-summary.json) is **397,360 bytes**, SHA-256 `febc422cdbbdf74c8a71d4bb064dffb284d5da87cc7e5798a969b20b45e313e7`, and records `overallStatus: primary-pass-regression-fail`. It binds this collector and reused collectors, the acceptance audit, candidate/source/archive/installed identity, normal-driver payload and separately compared installer metadata, immutable fault gate/receipt, both host handshakes/process lineages, complete native trace hashes, original guard files, actual retry source/profile bytes, historical log slices, current logs and the failed regression's partial results/safety cleanup. The dirty source check permits editor CRLF/LF normalization while requiring only the intended revision edit. Old profile bytes are reconstructed from the pinned deterministic profile format for comparison with historical size/hash, rather than presented as retained original bytes.

## Reproduction

Run from the pinned worktree/repository root with a new artifact directory for every attempted control. The host-loss launcher kills only its verified isolated extension-host instance and preserves unknown outputs; it needs permission to query and hold those native process handles. The test uses the normal isolated CLI and does not require GUI automation.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/host-loss-2026-11-08'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n02' # must be new
& $python -B scripts/variant/lifecycle/host-loss/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/host-loss/run.ps1 -WorkDir $work
```

The wrapper selects `abrupt-extension-host-loss`; do not pass `--scenario`. The primary driver has its own one-initial/one-retry sequence despite the shared preparation's cycle field. For a separate ordinary compiler attempt, use shared `scripts/variant/lifecycle/prepare.py` with the same pinned inputs, a new directory and `--scenario build-failure-retry --cycles 3`, followed by shared `run.ps1`. Preserve any first failure and investigate before rerunning.

Regenerate the retained summary without starting an editor or rerunning suites:

```powershell
& $python -B docs/research/host-loss-2026-11-08/summarize.py `
  --run (Join-Path $artifactRoot 'n01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

The collector can succeed at validating faithfully retained failed evidence; its exit status is not an all-controls-pass result. Inspect `overallStatus` and `compilerRegression.success`. No claim extends to native macOS, physical F5/menu routing, arbitrary descendants, active-build host loss, calibrated performance, error-free language-service/UI logs, or the full repeated qualification matrix.
