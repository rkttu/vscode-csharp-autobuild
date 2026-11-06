# Installed native build cancellation and concurrent retry control

This follow-up to [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) adds an installed-editor scenario for cancelling a real SDK build from VSCodium's progress notification, then retrying a dirty source with three concurrent callers while another Web session remains live. It adds test coverage and a fixture; the product runtime remains the version merged in [#30](https://github.com/rkttu/vscode-csharp-autobuild/pull/30), commit `989584bb3b906206ed8ca6b2b27b313ce3edf4e3`.

On November 6, 2026, final-fixture `run-03` passed the actual native Cancel UI scenario and three A launch/Stop cycles in 112.09 seconds, with editor exit code 0. It returned `[false, false, false]` for the three coalesced cancellation callers, then `[true, true, true]` for the dirty concurrent retry with one real build/session and fresh output. B retained its original PID/token/response/output, then completed final targeted cleanup. The unchanged default scenario also passed a separate two-cycle smoke control in fresh `run-04` (18.05 seconds, editor exit 0). The [compact evidence](evidence-summary.json) retains exact installed identity, UI observations/action receipt, external direct-build ownership, output log slices and all first failures. Each scenario has one fresh profile; this is partial evidence for #18.

## First failures and fixture correction

The first native attempt, `run-01`, reached a nonce-owned fixture marker but could not receive a UI Cancel action: the hidden test window did not appear in the UI automation window/app inventory. Its commands had already returned `false`; the scenario later failed its UI-receipt safety deadline. Failure cleanup released only the nonce/PID-verified fixture barrier and observed that marker PID exit; it stopped the captured B session. That marker PID was not independently established as the direct SDK build process. This is a failed control, **not a successful native cancellation result**. No click receipt was fabricated.

In the visible `run-02`, external process inspection identified the marker PID as Roslyn's MSBuild BuildHost. A language-service build had entered the unfiltered target first; the actual `dotnet build` then failed when writing the existing marker. The retained UI observation contains error notifications, with no Cancel click. Both first failures remain retained. The fixture was corrected to require the public command's `AssemblyName=FileApp` and exclude `DesignTimeBuild=true`, so language-service builds cannot enter or claim the barrier. Final runs additionally retain external process evidence tying the marker PID to the exact direct `dotnet build` command.

In `run-03`, the first click attempt failed because the UI state had been captured without screenshot geometry. A receipt was written prematurely, then withdrawn to `ui-cancel-action-attempt-01.json` with an explicit `ui-action-failure-01.json` record before a fresh observation and real action. The final `ui-cancel-action.json` is a distinct receipt written after the successful `sky.click` on Cancel element 855 at `2026-11-06T11:47:11.369Z`. Both failed-attempt records remain hashed. The actual click and the observed cancelled build phase, rather than the withdrawn receipt, establish this scenario's successful path.

## Native observations

External native process inspection before the click ties marker PID `33980` to `C:\Program Files\dotnet\dotnet.exe`, the exact A source/output and `-p:AssemblyName=FileApp`. It records the creation time and parent PID. Before/after UI accessibility records identify the unique nonce-titled isolated window and the Cancel control. Existing language-service project-loading error notifications for A/B also appear in these records. Their retained C# logs report `NU1100` for ILCompiler/ILLink/runtime packs while the isolated profile intentionally clears NuGet sources. This control therefore makes **no claim of an error-free notification UI or qualified language-service behavior**.

| Observation | Milliseconds from scenario start |
| --- | ---: |
| Cancellation command invocation | 11070.083 |
| Real SDK barrier readiness | 13248.581 |
| Three cancellation commands returned `false` | 81986.097 |
| Direct SDK PID first observed gone | 100975.972 |
| Exact cancelled output first observed absent | 100977.208 |
| A port successfully rebound | 100978.684 |

The cancelled build phase includes about 70 seconds waiting for the operator's UI action. The PID/output/port observations are delayed by the operator writing the final receipt about 19 seconds after command return. These are observation times, not shutdown latency measurements or performance budgets. They do not imply resources remained live until those checks.

## Scenario and evidence boundaries

1. Normally install the local candidate and pinned runtime dependency in a fresh isolated profile. The development path contains only the separate driver. Verify loaded extension identity and owned module hashes.
2. Launch A and B through the public registered command API with distinct loopback ports and tokens. Evaluate A's real source breakpoint, Stop A and check matching termination, PID exit, port rebind and exact owned-output/queue cleanup.
3. Leave B live, dirty A to enable an MSBuild barrier and issue three concurrent calls to `netcoredbg.debugActiveFile`. The command must save A and start exactly one actual SDK build.
4. The barrier runs inside the command's MSBuild task before compilation, writes its own PID and the isolated fixture's nonce, and waits. Its `AssemblyName=FileApp` and non-design-time conditions exclude language-service builds. The driver verifies the nonce/PID, one logged build and the live owned output, then writes `needs-ui-cancel.json`. External native process inspection confirms the direct SDK executable/command line before the UI action.
5. Select the unique isolated VSCodium window and click its actual progress **Cancel** button. Retain the UI observation/action trace and atomically write `ui-cancel-action.json` using the request's nonce and logical window title. The receipt is an operator attestation; its presence alone does not prove a UI action.
6. Require three `false` results, a cancelled build phase distinct from failure/timeout, no A session, direct build PID exit, exact output/queue cleanup and A port reuse. B must preserve its original PID/token/response/output.
7. Disable the barrier and change A's revision in an unsaved edit. Three concurrent retry calls must return `true`, share one logged build and one session, and serve the new revision from fresh output. Complete the remaining A Stop/retry cycles, preserving B, then Stop B.

No cancellation token or SDK runner is injected into the installed runtime. The barrier has a safety deadline; a failure-only release is allowed only after matching the marker's nonce and captured PID. A passing cancellation requires that release file to remain absent. The fixture uses an in-process task rather than a detached `Exec` child. Only the direct reported SDK PID is checked; there is no descendant-process claim.

The original direct CLI preflight verified that the barrier marker identified the actual `dotnet build` process and that an exact release allowed the build to finish. This verifies the earlier fixture's mechanics, not editor cancellation or the corrected design-time filter. A harmless `CS0162` task-wrapper warning was observed in this preflight; the final fixture removes its redundant return statement.

Three independent SDK controls of the final target (`SHA-256 17416084970a0078055eee1a9f4fcf58d9f1cac2aabbdaaf99166c3ecaf17073`) pass. The default assembly and `FileApp` with `DesignTimeBuild=true` do not create a marker. Regular non-design-time `FileApp` creates the marker in direct SDK PID `83864`, then exits 0 after nonce/PID/native-process ownership verification and release. None emits `CS0162`. Exact source/target inputs, command arguments, output logs, ownership and results are hashed in the summary. These fixture controls do not replace the actual editor Cancel check.

The new unit regressions cover three dirty-save callers declining together and retrying, plus cancellation during a pending build with repeated callers retaining ownership until child closure and a corrected concurrent retry. Strict Node tests pass **151 cases with zero skips**; Python helper tests pass **39 cases**. Independent source review and Node/PowerShell/XML syntax checks pass.

The final check collector initially reported empty Node counts because its regular expression excluded Node's Unicode information marker. The raw Node process exited 0 and reported 151 passes, 0 failures and 0 skips. The collector's report was corrected from the same retained stdout, without repeating the tests. The original report, script and hash manifest remain retained with the corrected report and all raw outputs. The evidence summarizer independently reads the raw Node/Python counts and checks their source hashes.

The driver observes output retention at the pre-Cancel barrier and output absence after command return. Those observations do not continuously establish deletion ordering during native shutdown. The unit regression covers that ordering in the controlled runtime model. Starting debugging through the command API and clicking an actual Cancel button are separate routes; neither establishes physical F5 or menu launch behavior.

## Inputs

| Input | Recorded value |
| --- | --- |
| Editor / SDK / observed app runtime | Native Windows ARM64 VSCodium `1.143.17232` (API `1.143.1`); SDK `10.0.403`, Core runtime `10.0.14` |
| Preparation checkout HEAD | `989584bb3b906206ed8ca6b2b27b313ce3edf4e3` |
| Final native `run-03` local VSIX SHA-256 | `db8eb78d5f6af87e562316793030e38d788278e696cb96caa83bcd19ba6887cb` |
| Default `run-04` local VSIX SHA-256 | `82d3c3300b54ea8a50f0d5cf7666e01486a1f3ef2600515d8209ffc1a9052d87` |
| Historical failed `run-01` local VSIX SHA-256 | `03cfb9f3baa6704c874ae1399ff1d3141dbfd2a2c1a9b923d138d64571e98782` |
| Local build ID | `56d34a8f8a5d1081451a3ddca2f1fa265eeb738caaf91c7f85764ab9987af5a6` |

The local-only candidate retains version `11.7.18004`; its 736 non-owned payload entries remain unchanged. Owned runtime hashes/build ID are identical across these runs; separate ZIP archives have distinct recorded SHA-256 values. It is not published and does not establish extension update completion. Full qualification, numeric latency calibration and publication gates remain in [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). Actual host shutdown/crash, macOS, physical F5, descendant handling and the complete repeated matrix remain outside this control.

## Reproduction

Use the pinned inputs below and a fresh work directory for every attempt. Preserve failures before changing the harness or attempting another profile.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/native-build-cancellation-2026-11-06'
$work = Join-Path $artifactRoot 'run-new'
& $python scripts/variant/lifecycle/prepare.py `
  --base-vsix 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix' `
  --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix' `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario native-build-cancel --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work -ShowWindow
```

`-ShowWindow` explicitly requests a visible interactive test window; the default remains hidden. In this run it was enabled only after the user requested the visible test. A hidden window absent from the UI inventory cannot satisfy the UI action requirement.

Before clicking, retain `sdk-build-process.json` with `schema=1`, `directSdkBuild=true`, `pid`, `observedAtUtc` and `exactProcess` containing the native `ProcessId`, `ExecutablePath` and `CommandLine` (including exact A source/output). Preserve creation time and parent PID as additional ownership evidence. Retain `ui-observation.json` with `schema=1`, `actualCancelClicked=true` only after the real action, and `before`/`after` window-state records containing their returned `window` and `accessibility` data. The `before` tree must contain the selected Cancel element and the unique window title.

After the real Cancel click, atomically create the receipt using the nonce/title from `needs-ui-cancel.json`. For example, with `$observedAction` fields filled from the actual UI action record:

```powershell
$request = Get-Content (Join-Path $work 'needs-ui-cancel.json') -Raw | ConvertFrom-Json
$receipt = @{
  schema = 1; nonce = $request.nonce; windowTitle = $request.windowTitle
  action = 'click-cancel'; tool = 'sky.click'
  windowId = $observedAction.windowId; elementIndex = $observedAction.elementIndex
  clickedAtUtc = $observedAction.clickedAtUtc
  observedWindowTitle = $observedAction.observedWindowTitle
  observation = 'ui-observation.json'; buildProcessProof = 'sdk-build-process.json'
}
$temporaryReceipt = Join-Path $work 'ui-cancel-action.json.tmp'
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryReceipt
Move-Item -LiteralPath $temporaryReceipt -Destination (Join-Path $work 'ui-cancel-action.json')
```

For a separate default smoke regression, prepare a fresh directory using `--scenario web-lifecycle --cycles 2`. Safety deadlines are fixture limits, not calibrated product latency budgets. Large VSIX/profile/trace files stay in local validation artifacts; the compact evidence summary binds their exact hashes and source identities.

Regenerate the compact summary from the original retained layout:

```powershell
& $python docs/research/native-build-cancellation-2026-11-06/summarize.py `
  --runs (Join-Path $artifactRoot 'run-03') `
  --failed-runs (Join-Path $artifactRoot 'run-01') (Join-Path $artifactRoot 'run-02') `
  --normal-control (Join-Path $artifactRoot 'run-04') `
  --gate-preflight (Join-Path $artifactRoot 'gate-preflight') `
  --fixture-controls (Join-Path $artifactRoot 'fixture-controls') `
  --checks (Join-Path $artifactRoot 'checks')
```

The summarizer validates the current runtime/candidate identity and final harness, the executed preparation snapshot, native process/UI provenance and exact UTF-16-offset log slices. It rejects a summary that omits a retained failed sibling profile. UI observations and receipts remain operator attestations linked to the actual UI tool record.

The automated Node and Python checks can be run independently from the repository root:

```powershell
$node = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $node --unhandled-rejections=strict --test 'scripts/variant/file-based-apps/test-*.cjs'
& $python -m unittest discover -s scripts/variant -p 'test_*.py' -v
```
