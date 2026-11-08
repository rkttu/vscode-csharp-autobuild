# Actual progress Cancel during a held debugger handoff

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up adds the optional `native-handoff-cancel` control. An exact-token test provider holds a valid editor debug configuration after a real successful build and Web preparation. An actual click on the editor's **Debug C# file → Starting netcoredbg → Cancel** progress control releases three foreground callers while that configuration remains held. The five product modules remain unchanged from merged [PR #42](https://github.com/rkttu/vscode-csharp-autobuild/pull/42), commit `2b9b01252f85afd6f554c3d5b149a936845c5a18`. No package is published.

Native control `n01` passes in **64.04 seconds**, with editor exit 0. Independent compiler-error regression `c01` passes in **42.78 seconds**, also with exit 0. Strict Node **228/228** and Python **39/39** checks pass, without failed, skipped or cancelled intended cases. Neither installed-editor attempt has an unexpected failure or test safety cleanup.

## Held output, real UI cancellation and late native cleanup

The candidate and pinned runtime dependency are normally installed in a fresh Windows ARM64 VSCodium `1.143.17232` profile (API `1.143.1`), using SDK `10.0.403`. Initial A and B Web sessions verify their distinct HTTP token/PID ownership; A exercises its source breakpoint/evaluation. A is then stopped with exact session/PID/port/output cleanup while B remains active.

1. Preserve valid A source, write a normal HTTP profile with a fresh application token, and invoke the public command three times. One real build and Web preparation reach one test-only `coreclr` provider callback. The callback retains the original valid configuration and samples the generated DLL/PDB metadata, then waits on a gate before adapter creation. The provider changes timing; it does not reject startup or inject a cancellation token.
2. The UI request binds the held phase, profile nonce, application token and generated program/output. Through `@oai/sky`, the operator observes the uniquely titled isolated window and clicks accessibility element **814, Cancel**, in the same notification container as **Debug C# file: Starting netcoredbg**. The receipt records the returned application/window identity, selected element, action timestamps, and hashes of fresh before/after observations.
3. The three command results are `[false, false, false]`. At the post-return sample, the provider remains pending, the editor initialization token is still **not cancelled**, DLL/PDB bytes retain their original sizes/hashes, the output exists, terminal queues are empty and A's port is reusable. B retains its exact session, PID, token, HTTP body and output. The owned command logs cancellation of `Starting netcoredbg`, without a failed/timeout/declined-start diagnostic.
4. Release the **same original configuration object**. A real late editor/native session initializes and receives `launch`; this run reports debuggee PID **30500**. Native `terminate` request 5 is followed by successful `configurationDone` request 6 and `disconnect` request 8. The owned runtime logs its exact-session follow-up Stop after adapter configuration. The control sends no Stop or fallback for this cancelled attempt. Protocol requests alone do not identify their API caller; the unchanged runtime cancellation path, exact diagnostic and controlled trace support the product Stop attribution.
5. Observe adapter exit 0, matching editor termination, the exact reported PID no longer alive, output/queue removal and a reusable port. Dispose the test provider once, then make a dirty A revision and invoke three commands again. `[true, true, true]` shares one saved build, one fresh session/token/output and the correct HTTP revision while B survives. Finish three ordinary A Stop cycles and B's final Stop.

The measured sequence after foreground return is held output at `51225.5 ms`, original-config release at `51231.8 ms`, late editor start at `51671.3 ms`, editor termination at `52407.0 ms`, reported PID exit observed at `52412.1 ms`, and output removal observed at `52444.9 ms`, all relative to control start. These are observations from the controlled gate and UI interaction, not a product latency budget.

The saved post-click accessibility tree still contains cached Cancel text. The collector preserves that observation and does not require text disappearance. Original JPEG screenshot files are bound by encoded-byte hashes; they are not reopened by the collector. The UI receipt is a tool/operator attestation linked to the saved observations. Returned window metadata supplies an application selector, window ID and title, but no process PID; no UI-to-process PID claim is made.

This run has a positive DAP process event, captured-session PID and independent exit observation for PID 30500. The harness also records whether a future fast teardown reaches a DAP launch or reports a PID. Missing process events would not establish OS-process absence. Retry here follows late termination/cleanup and provider disposal; retry while that old handoff remains pending is outside this control.

## Retained evidence and fixture limitation

Raw profiles and logs remain under `validation-artifacts/handoff-cancel-2026-11-08/`, using native `n01`, independent compiler regression `c01` and unit `tests`. [summarize.py](summarize.py) validates exact product/archive/installed bytes, held callback/configuration/artifact metadata, actual UI request/receipt/observation bindings, foreground output retention, original-object release, native transcript, captured PID/termination/cleanup, provider disposal and corrected retry/B checkpoints. [evidence-summary.json](evidence-summary.json) is **138,900 bytes**, SHA-256 `b81d2b59cadcdedab7bbf545a932577ac05e22142b948f54b0cdd87cc46278ad`.

| Retained input | SHA-256 |
| --- | --- |
| `n01` local candidate ZIP | `be3b320d3f6c71f2e3c29b1a9b2958489872adcc8e3540e049071833eeab3510` |
| `c01` local candidate ZIP | `acb135a6dac6a436909e1b7388d7769cd6fbfe2913d939e2e05e4b21a7f240af` |
| Shared content build ID | `c4ff1765ce1411e26088e9e5805aa62f3aefd6f22fd470ce62f4a185e4f94c57` |
| Unit source/attempt manifest | `56e7645393c6aa613c001aae215e636face0fb55fc9fad62222b7fdb21bd259b` |

The unit manifest retains all **48** tracked or new unignored `scripts/variant` source byte copies, pre-run hashes, final verification time, exact argv, complete logs/results and verification-runtime hashes. The collector checks historical/current bytes and the complete source set. Native output slices retain exact UTF-16 boundaries, prefix/tail hashes and JSON-quoted process arguments. DLL/PDB metadata was sampled before normal owned cleanup; artifact bytes are not retained after deletion.

Existing language-service project-load notifications for A and B are visible in both UI observations. The retained `C#.log` (57,954 bytes; SHA-256 `31c8f21cd0b88e42a79114113276aed6ba6066b91ceecd604c11f4ae64e1df4e`) records separate file-based-program restores with `NU1100` errors for AOT/linker/runtime packages. Both prepared `NuGet.Config` files explicitly clear package sources, whereas every owned debug build uses `-p:PublishAot=false` and succeeds. Those differing results are consistent with this offline fixture and restore settings; they do not demonstrate a handoff/adapter defect. The summary binds the two configuration files and diagnostic samples. Language-service readiness and error-free UI/logs are not qualified by this control.

## Reproduction

Run from the repository root with pinned inputs and a fresh short artifact name. The native control requires a visible isolated editor and a separate actual `@oai/sky` UI action/observation recorder.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/handoff-cancel-2026-11-08'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n02' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario native-handoff-cancel --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work -ShowWindow
```

While the launcher waits at `needs-ui-cancel.json`, capture fresh UI state in the window identified by `expected.json`'s unique title, click that progress notification's Cancel element through `@oai/sky`, and save the returned observations and original screenshot bytes once. Write `ui-cancel-action.json` from that action's actual data. The retained summary's `handoffCancellation.ui` shows the complete schema: gate nonce/token/phase/stage, `automation`/`method`/control labels, returned window, action UTC bounds, target element, and exact `ui/before.json`/`ui/after.json` paths and hashes. Each observation retains the gate identity, UTC time, returned window, accessibility state and screenshot metadata. The shell launcher alone waits for this external UI action and receipt.

For the separate compiler regression, prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3`, then use the ordinary launcher without a UI recorder. Preserve each attempted profile. Regenerate the summary without opening an editor or rerunning suites:

```powershell
& $python -B docs/research/handoff-cancel-2026-11-08/summarize.py `
  --run (Join-Path $artifactRoot 'n01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

This local command-API/control-provider slice adds no release qualification. Native macOS, physical F5/menu, notification dismissal, certificate/trust cancellation, arbitrary host loss, descendants and the full repeated qualification matrix remain outside it. Provider-chain relative ordering is not asserted; the recorded exact-token callback is the observed gate.
