# Graceful runtime disposal

A local Windows ARM64 VSCodium control passed pending-save, active-session and late-session disposal with the real SDK/native adapter in `run-10` (15.94 seconds). It exercises the early-Stop ordering that failed before the readiness repair. The control directly activates the installed runtime in helper contexts while B uses the installed public command; this is same-host evidence, not actual extension/host shutdown qualification.

This change gives an FBA runtime activation a defined graceful-disposal path for [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18). Disposal unregisters its command immediately, rejects retained command callbacks, checks disposal again after pending cleanup/save, aborts its controllers, and requests Stop only for its exact owned active or late-starting sessions.

The runtime retains its lifecycle listeners and output while original debugger starts, matching terminations, pending operations, cleanup and background recovery remain unsettled. Once known work drains, those resources are released once. Uncertain starts, failed Stop requests or missing termination events preserve ownership/output rather than guessing that a debuggee is gone. This is an in-process policy; an exiting or crashed host cannot be assumed to wait for its asynchronous work.

An owned tracker correlates a successful `configurationDone` response with its request. When the first Stop was actually dispatched before that readiness and the exact cancelled session has not terminated, the runtime permits one follow-up Stop after the first settles. Ready-first sessions keep one Stop; duplicate readiness responses cannot form a retry loop. There is no fixed sleep, and an unavailable tracker API does not create inferred readiness.

## Control scope

The [control](control.cjs) uses a normally installed local candidate and its real SDK/native adapter. It directly loads the installed `runtime.cjs` and activates separate helper contexts in the same live editor host. Wrappers gate the completion of real document save and debugger start calls; SDK processes and the native debugger remain real. An unrelated B Web app starts through the installed public command.

- Active A: dispose its helper twice, then verify its exact session/PID, port and output are released while B remains live.
- Late A: hold its original debugger-start request, dispose the helper, verify the foreground returns `false` while output and both lifecycle observers remain, then release the real start and observe targeted termination/cleanup.
- Pending save: hold a real dirty source save, dispose, complete the save, then verify `false` with no SDK discovery or debug start.

Instrumented controls run B → pending save → active A → late A → B Stop so a late timeout does not prevent the independent save check. This diagnostic ordering change does not resolve a native late-start failure.

The final counters require one command unregistration, one output disposal, one disposal of each lifecycle listener and owned tracker factory, zero writes after output disposal, no error UI request and `false` from each retained disposed command. PID exit is claimed only when a PID was captured; active A and B also supply verified HTTP PIDs. These controls do not represent actual extension/host shutdown, host crash, physical F5, macOS, a process-tree test or release qualification.

## Native observations

| `run-10` helper | SDK discovery | Debug start | Real save | Exact Stop requests |
| --- | ---: | ---: | ---: | ---: |
| Pending save | 0 | 0 | 1 | 0 |
| Active A | 1 | 1 | 0 | 1 |
| Late A | 1 | 1 | 0 | 2 |

All helper resources drained once with zero post-disposal output writes and `false` from retained command callbacks. Active A, late A and B had captured PIDs that exited, with matching editor termination, port rebind and output/queue cleanup. The save case created no session. B preserved its PID/token/HTTP response/output through the helper cases before its final Stop.

The native ordering matters. In the failing `run-06`, `terminate` was acknowledged before `configurationDone`, but the session survived until control-failure cleanup. Repaired `run-10` repeats an early `terminate` request, then observes successful readiness and issues its one follow-up Stop:

| `run-10` event | Monotonic milliseconds |
| --- | ---: |
| Early `terminate` request | 14283.094 |
| `configurationDone` request | 14283.572 |
| Early `terminate` success | 14283.836 |
| `configurationDone` success | 14446.997 |
| Follow-up exact API Stop | 14447.315 |
| `disconnect` request | 14448.085 |
| Native exit / termination | 14481.878 / 14482.328 |

Matching editor termination, captured PID exit and port/output cleanup follow, without the safety-timeout cleanup intervention. This records the repaired sequence without assigning sole cause to an editor/adapter component. The separate passing `run-09` (15.52 seconds) had different ordering: native termination preceded its follow-up API Stop, so that sample alone is not causal recovery evidence. Both profiles and all earlier failures remain recorded; this is not a qualification pass-count reset.

The final installed-command regression (`run-08`) also passes: two ordinary A cycles, an expected real compiler failure, corrected concurrent requests sharing one build/session, and B cleanup in 19.93 seconds. `run-03` is retained as an earlier ownership-fix control with its distinct runtime hash, not relabelled as final-repair evidence.

| Final input | Recorded value |
| --- | --- |
| Editor / SDK / observed app runtime | VSCodium `1.143.17232` (API `1.143.1`), native ARM64; SDK `10.0.403`, runtime `10.0.14` |
| Runtime SHA-256 | `385aa60fc23193b10716452207ea89d8dfdc7f82c6f2220fcd70eb410178ad98` |
| `run-10` local VSIX SHA-256 | `29b4c36aecd08c1128513fc930a17b0a9c645e0ab5dcc5a4e009000a14f8c5a2` |
| Local content build ID | `3e2f65bd57c179cd4c19dd5de7e2b62e3e3c6769ce6dd01411cec4467122d5ed` |
| Preparation checkout HEAD | `a9ae67582ecc04aef9beacc64eff96b984b87ae7` |

The [summary](evidence-summary.json) binds installed modules and executed driver copies to the candidate and `controlPreparation` hashes, preserves all failed native attempts, and distinguishes historical/final sources. The checkout HEAD predates the local additions; exact hashes identify the tested bytes. The 736 non-owned payload entries remain unchanged. Single-run durations are observations, not product latency budgets.

## Regression and first-failure evidence

The initial ten disposal regressions fail the original runtime at `a9ae67582ecc04aef9beacc64eff96b984b87ae7`. They cover pending save/classification/cleanup, late start outcome/event ordering, active-session Stop, rejected Stop with uncertain output, recoverable terminal deletion failure and reentrant cleanup. Their before/after runs use identical test-fixture bytes. Earlier nine-case and ten-case snapshots remain retained separately. The baseline runner uses `--test-force-exit` after the expected assertion failures because the old runtime leaves pending timers; the passing full strict suite uses normal exit.

The initial ownership fix passed 141 strict Node tests without skips and 39 Python helper tests. Its evidence stays historical when the readiness repair changes the runtime. The summary hashes the exact runtime/test files, test commands and raw before/after output. Native failures are also retained:

| Control | First failure and investigation |
| --- | --- |
| `run-01` | The editor API's package JSON omitted installer-private `__metadata`; the raw installed file contains it. Installation identity now uses that file plus separate public API matching. No SDK cases ran. |
| `run-02` | Spreading the editor API read a proposed getter after B became ready, before helper SDK cases. The control now exposes only the stable APIs it needs. Its result was written before a matching B termination was recorded; that file is not termination/PID-exit proof. |
| `run-04` | Active and late A cases passed, then the document Proxy violated the frozen `save` property invariant. The gate never opened and the control safety timer expired. An explicit document facade now gates the real save, with fail-fast waiting. This was a control error, not a product SDK timeout. |
| `run-05` | Active A passed, but the late native session did not terminate during the disposal phase. It terminated and released its PID/output after control-failure cleanup. This is an unexpected native failure, separate from the integration defects above; its timeout and later cleanup remain recorded. |
| `run-06` | Instrumentation reproduced the native late-session failure: the adapter acknowledged `terminate` before `configurationDone`, but termination arrived only after cleanup `disconnect`. The sequence supports the readiness repair without assigning sole cause to an editor/adapter component. |
| `run-07` | A control bound assertion read a nonexistent internal `stopRequests` field after the save checks. The serialized helper count correctly reported zero from its empty `stopOutcomes` array. The assertion now reads that array length; its expected limits are unchanged. |

A later successful control does not erase those failures or their underlying helper errors.

Eight additional adapter-configuration cases exercise correlated readiness, serialized bounded retry, ready-before-dispatch behavior, failed/unrelated responses, retry rejection, termination ordering and missing-API compatibility. Against the initial ownership fix, seven fail and the compatibility case already passes. All eight pass in the final full strict suite of **149 tests**, with no skips; the Python helper suite passes 39. The initial 10-case/141-test evidence and final focused/full evidence retain separate source hashes.

## Reproduction

Use native Windows ARM64 VSCodium `1.143.17232` and SDK `10.0.403`, with the pinned base VSIX/runtime dependency from the [installed Web control](../web-lifecycle-2026-11-05/README.md). Run from a checkout containing the final runtime and controls. Choose a fresh work directory and retain prior failures.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/graceful-disposal-2026-11-06'
$work = Join-Path $artifactRoot 'run-11' # must be new
& $python docs/research/graceful-disposal-2026-11-06/prepare.py `
  --base-vsix 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix' `
  --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix' `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

The custom preparer writes control source hashes into `controlPreparation` and updates the copied driver hashes before installation or launch. Only the separate empty driver uses `extensionDevelopmentPath`. The candidate is local-only version `11.7.18004`; it is not published. The isolated launcher and safety timeouts are reused without claiming calibrated product budgets.

Regenerate the recorded evidence from its original local artifacts with:

```powershell
& $python docs/research/graceful-disposal-2026-11-06/summarize.py `
  --run (Join-Path $artifactRoot 'run-10') `
  --diagnostic-runs (Join-Path $artifactRoot 'run-09') `
  --failed-runs (Join-Path $artifactRoot 'run-01') (Join-Path $artifactRoot 'run-02') (Join-Path $artifactRoot 'run-04') (Join-Path $artifactRoot 'run-05') (Join-Path $artifactRoot 'run-06') (Join-Path $artifactRoot 'run-07') `
  --regression-run (Join-Path $artifactRoot 'run-08') `
  --historical-regression-runs (Join-Path $artifactRoot 'run-03') `
  --test-artifacts $artifactRoot
```
