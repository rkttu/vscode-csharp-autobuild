# Installed native .NET host failure and same-file retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up adds an optional `native-host-failure-retry` scenario to the installed-editor lifecycle control. A deliberately invalid per-file `DOTNET_ROLL_FORWARD` value causes a real .NET host startup failure through the normally installed bundled debugger. The five product modules remain unchanged from merged [PR #39](https://github.com/rkttu/vscode-csharp-autobuild/pull/39), commit `c712ede7edb303d42b95d083a724315adf44aa3d`; no package is published.

The native control `n01` passes in **35.76 seconds** on Windows ARM64 VSCodium `1.143.17232` (API `1.143.1`) with SDK `10.0.403`. Independent compiler-error regression `c01` passes in **28.41 seconds**. Both editor processes exit 0, with no unexpected installed-editor failure or test safety cleanup. Strict Node **228/228** and Python **39/39** checks pass, without failed, skipped or cancelled intended cases.

## What was observed

1. Normally install a local candidate and the pinned runtime dependency in a fresh isolated profile. Launch independent A and B Web sessions through the public command API, verify HTTP token/PID ownership, and exercise A's source breakpoint/evaluation. Stop A and wait for its matching editor termination, PID exit, reusable port and owned output/queue cleanup.
2. Preserve valid saved A source and write its ordinary HTTP `.run.json` profile with a fresh token and `DOTNET_ROLL_FORWARD=LIFECYCLE_INVALID_ROLL_FORWARD`. This changes only A's debuggee environment. The real SDK build, generated DLL/PDB/runtimeconfig, owned `program`/output paths and installed native adapter remain intact. No editor configuration-rejection provider is registered.
3. Invoke the public command three times concurrently. One successful SDK build and Web preparation lead to one native adapter and captured session. **The three command results are `[true, true, true]` and DAP `launch` succeeds.** The host then reports `Invalid value for environment variable 'DOTNET_ROLL_FORWARD'.` on DAP stderr, and native `configurationDone` request 5 receives a correlated failure (`0x80004005`). API acknowledgement and successful application startup are therefore separate observations.
4. Observe native adapter exit code 0 and the matching editor termination without a test Stop request. The failed output disappears, both terminal queues are empty, and A's port can be rebound. B retains its exact session, PID, token, HTTP response and output.
5. Restore the normal per-file profile, make a valid dirty source revision, and invoke three concurrent commands again. `[true, true, true]` shares one saved build and one fresh session/token/output, and the HTTP response serves the corrected revision. Check B again, complete three A Stop cycles and stop B with exact owned cleanup.

The failure is deliberately induced by the fixture but is handled by the real .NET host and native DAP adapter. The [.NET host source](https://github.com/dotnet/runtime/blob/v10.0.0/src/native/corehost/runtime_config.cpp#L294) validates the environment value. The [pinned debugger's configuration phase](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/protocols/vscodeprotocol.cpp#L514) and [process/attach path](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/debugger/manageddebugger.cpp#L633) explain why a launch acknowledgement can precede failure. This does not demonstrate an adapter executable crash.

No failed-token DAP `process` event or PID is captured. The host can exit before CoreCLR attach and the debugger's process event. This run does **not** independently prove a failed-host PID exited or establish global OS-process absence. Its direct observations are the native diagnostic/response, adapter exit, exact editor termination, resource cleanup and reusable port.

## Retained evidence

Raw profiles and logs remain under `validation-artifacts/native-host-failure-2026-11-07/`, using `n01`, independent compiler regression `c01` and `tests`. [summarize.py](summarize.py) reuses the prior Web/compiler and identity validators, then checks exact source/profile snapshots, generated artifact metadata, matching DAP request/response sequences, automatic termination, cleanup, corrected retry and discrete B checkpoints. [evidence-summary.json](evidence-summary.json) is **113,253 bytes**, SHA-256 `7101a905055a96c7d68ea21686d8958c45342cdf93c6d5266bdabbd9d92a74c7`.

| Retained input | SHA-256 |
| --- | --- |
| `n01` local candidate ZIP | `57fc69b677d757f1b52ff96a62117e3b78b2747f0f6bd615a78e9b6c99036838` |
| `c01` local candidate ZIP | `9440eaf20caaf2743a87da4011f0f3fa2e56cf65aa5cc4b5f4dfbbfafd6e331a` |
| Shared content build ID | `eacc103bd794dc8305aea1fbe75f6c6ba0a604449989085498e6f9989bc855c5` |
| Unit source/attempt manifest | `27656c06bdbb1360648910ddb7360f8ed0c96491c57239fdc99f53d3db2d6d84` |

The unit manifest retains 46 pre-run source byte copies with hashes, a final verification timestamp, exact argv, complete logs/results and verification-runtime hashes. The collector checks both current source and retained copies. DLL/PDB/runtimeconfig metadata was sampled before cleanup; only runtimeconfig bytes are retained. Native output log slices retain their exact UTF-16 boundaries and prefix/tail hashes, with JSON-quoted process arguments.

## Reproduction

Run from the repository root with the pinned inputs and a fresh short artifact name. Retain every attempted profile.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/native-host-failure-2026-11-07'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n02' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario native-host-failure-retry --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

Prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3` for the independent compiler regression. The launcher restores its process environment and refuses to reuse an attempted profile. Regenerate the summary without rerunning suites or opening an editor:

```powershell
& $python -B docs/research/native-host-failure-2026-11-07/summarize.py `
  --run (Join-Path $artifactRoot 'n01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

These are local command-API controls with discrete resource/liveness observations, not a calibrated latency budget or release qualification. Physical F5/menu, native macOS, notification UI, certificate/trust/UI cancellation, arbitrary active-host loss, descendants and the full repeated qualification matrix remain outside this slice. Stop-time adapter diagnostics remain retained alongside the behavioral assertions.
