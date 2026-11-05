# Installed compiler-failure and same-file retry control

On November 5, 2026, `run-02` passed an actual compiler-failure/corrected-retry scenario through the normally installed extension in native Windows ARM64 VSCodium. It completed three A launch/Stop cycles, one expected compiler failure and a final B Stop in 24.33 seconds. The unchanged default scenario also passed a separate two-cycle smoke control in `run-03` (16.19 seconds). Both editors exited with code 0.

The [compact evidence](evidence-summary.json) extends the [earlier Web lifecycle control](../web-lifecycle-2026-11-05/README.md) for [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18). It retains failed-build and concurrent-command evidence, exact installed identity/hashes, normal session/PID/port/output cleanup observations, and raw result/trace/log hashes. Each scenario has one fresh profile; these controls do not constitute the full qualification matrix.

The candidate is local-only and the invocation route is the command API. The driver does not replace the target runtime or dismiss error notifications. This does not establish notification visibility, physical F5/menu operation, macOS behavior, crash recovery, process-tree cleanup or release qualification.

## Scenario

1. Launch A and B with distinct loopback HTTP ports and launch tokens. Bind/evaluate A's real source breakpoint, then stop A and independently confirm matching termination, PID exit, port rebind and owned-output/queue cleanup.
2. Leave B live. Introduce an undefined identifier in unsaved A source and execute the installed command. Require `false`, the source saved, a real compiler diagnostic and the failed build phase in the editor's output log, no matching debug session, failed-output cleanup and an available A port.
3. Verify B retains its PID/token/response/output. Correct A with a workspace edit and invoke the command concurrently three times. Require successful callers, one real build and one session, fresh output, the corrected revision and the original A port.
4. Complete the configured A stop/retry cycles, preserve B after each, then stop B with the same resource assertions.

The failed build's exact output path comes from the actual logged build arguments. Windows URI drive-letter casing is not used to guess a directory to inspect. The test leaves notifications untouched and observes the command's ability to retry; it does not infer visible UI state.

## Observed result

The compiler reports `CS0103` for `__missingLifecycleValue`, and the output records one failed `Building file-based app` phase. The command returns `false`, the broken source is saved, no matching session is observed, and the exact failed output is absent when checked. B retains its PID/token/response/output. Correcting the dirty source produces `[true, true, true]` from three concurrent command requests, exactly one logged build, one captured session and fresh output serving revision `retry-1`.

| Observation | Milliseconds |
| --- | ---: |
| Failed command invocation → `false` return | 2683.397 |
| Return → failed output first observed absent | 1.074 |
| Return → A port successfully rebound | 1.903 |
| Complete dirty-correction/retry phase | 3948.345 |

These are single-run observations, not latency budgets. Output/port assertions occur after command return and log flushing; they do not timestamp deletion or prove its exact ordering before return. Full phase and ordinary Stop observations remain in the summary.

| Input | Recorded value |
| --- | --- |
| Editor / SDK / observed app runtime | VSCodium `1.143.17232` (API `1.143.1`), native ARM64; SDK `10.0.403`, Core runtime `10.0.14` |
| Preparation checkout HEAD | `4898eb6a9ed93c2f9ad730a6de5091c0f75be5f7` |
| Main local VSIX SHA-256 | `ed719f1dbca2011b5cc7a66a7c049849331b97c87180809294f5de385583cef6` |
| Local build ID | `b1d7d75dfe8fcba43abac6397b9606f04739b3cb3db1b4af881418f76485ee32` |

The candidate retains local-only version `11.7.18004`. Its five owned runtime-module hashes match the previous control, and the 736 non-owned payload entries remain unchanged. No production runtime change or publication is included. Exact editor, SDK, dependency, VSIX, installed-path and harness provenance are recorded in the summary; source hashes bind the uncommitted harness additions used at preparation time.

The summary hashes the numbered `3-C# File Debugging.log` file and reconstructs the driver's exact prefix/tail hashes with its UTF-16 offsets. This links the compiler error, phase and output path to the retained raw log. Stop-time adapter `read error` and failed `threads` diagnostics remain recorded and unclassified, as in the earlier control.

Independent review found no blocking defect; strict Node tests passed 131 cases without skips and Python helper tests passed 39, with syntax checks. `run-01` was prepared but superseded during pre-launch review; its unexecuted metadata and candidate hash are retained separately. There were no unexpected editor failures in these controls.

## Reproduction

Use native Windows ARM64 VSCodium `1.143.17232` and SDK `10.0.403`, with the pinned base VSIX and runtime dependency from the previous control. Choose a fresh directory and preserve every earlier attempt.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/build-failure-retry-2026-11-05'
$runtimeVsix = 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'run-04' # must be new
& $python scripts/variant/lifecycle/prepare.py `
  --base-vsix 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix' `
  --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtimeVsix `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario build-failure-retry --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

The inherited launcher isolates editor, extension, SDK/NuGet and temporary state, preserves the first attempt's files, and restores its caller's process environment. Safety timeouts are not calibrated product budgets. Large VSIX files and full traces stay local; the compact summary retains their hashes, exact loaded identity, ordinary cleanup timings and the new failed-build/coalescing evidence.

For the separate default smoke control, prepare a second fresh directory with `--scenario web-lifecycle --cycles 2`, then run the same launcher. Regenerate the recorded summary from its original local artifact layout with:

```powershell
& $python docs/research/build-failure-retry-2026-11-05/summarize.py `
  --runs (Join-Path $artifactRoot 'run-02') `
  --normal-control (Join-Path $artifactRoot 'run-03') `
  --preflight-dirs (Join-Path $artifactRoot 'run-01')
```
