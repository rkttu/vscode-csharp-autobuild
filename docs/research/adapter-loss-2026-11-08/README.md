# Installed native adapter-process loss and same-file retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up adds the optional `native-adapter-loss` lifecycle control. After two real Web debug sessions are ready, an isolated helper deliberately kills only A's independently verified native adapter process. The five product modules remain unchanged from merged [PR #40](https://github.com/rkttu/vscode-csharp-autobuild/pull/40), commit `2ef05e2d2c872774f8b6a54da0e107ada0b6cd91`. No package is published.

Native control `n01` passes in **50.50 seconds**, with editor exit 0. Independent compiler-error regression `c01` passes in **40.10 seconds**, also with exit 0. Strict Node **228/228** and Python **39/39** checks pass. Neither installed-editor attempt has an unexpected failure, observed product gap or test safety cleanup.

## Fault identity and observations

The candidate and pinned runtime dependency are normally installed in a fresh Windows ARM64 VSCodium `1.143.17232` profile (API `1.143.1`), using SDK `10.0.403`. Initial A and B launches have distinct session IDs, native DAP process IDs and HTTP ownership tokens. A exercises its source breakpoint/evaluation before the fault.

The helper checks the installed adapter's path and SHA-256 against the prepared candidate archive. It identifies A's adapter through A's captured debuggee parent PID, then checks executable paths, command lines, creation times, distinct B identities and complete editor ancestry to this isolated launcher. After obtaining an OS process handle, it rechecks the same identities and nonce/PID/revision HTTP responses immediately before killing that one adapter. It does not request a process-tree kill, rename a binary, modify a profile or terminate a debuggee directly.

The measured sequence is:

1. A's native adapter PID `92560` exits after the deliberate Kill. The helper records signed OS exit code `-1`; the editor tracker records `4294967295`. The collector verifies their equality modulo 32 bits.
2. In the first three resource samples, A's captured debuggee PID `44872` no longer responds to signal zero, its HTTP request fails and its port can be rebound. The editor session has **not yet** emitted its termination event, and A's program/output remain present. B retains its original session, PID, token, HTTP body and live output at every sample.
3. The matching editor termination arrives at `26149.8 ms` after control start. At the settlement sample (`26221.5 ms`), A's program/output are absent and both terminal queues are empty, while its PID/HTTP/port observations still show release. No sample finds an owned A HTTP response after editor termination or while A's output is absent.
4. A valid dirty source revision retries through three concurrent public commands. `[true, true, true]` shares exactly one real SDK build, one fresh session/token/output and the expected HTTP revision. B survives a separate post-retry checkpoint. Three later A Stop cycles and B's final Stop release their exact owned resources.

The initial A session has no **test Stop request**. The editor does send DAP `disconnect` request 21 after adapter exit; that request remains in the transcript. No DAP `exited` or `terminated` event is received for initial A. Debuggee exit evidence comes from the separate captured-PID, HTTP and port observations, rather than missing DAP events.

The native module transcript identifies `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\10.0.14\System.Private.CoreLib.dll`. The [Windows CLR controller source at the `v10.0.14` commit](https://github.com/dotnet/runtime/blob/6aa72daa24f66c01c3d7b6a32519e9d21396deec/src/coreclr/debug/ee/rcthread.cpp#L934) takes a fatal termination path when its controlling debugger process handle is signaled. These independent local observations are consistent with that path; they do not prove that the exact source branch executed or establish equivalent behavior on other platforms.

This control demonstrates an intentionally forced native adapter-process loss, rather than a spontaneous crash reproduction. Resource checks are discrete samples, not continuous monitoring. Initial faulted A is recorded separately from the later three ordinary A Stop cycles.

## Retained evidence

Raw inputs, profiles and logs remain under `validation-artifacts/adapter-loss-2026-11-08/`, using `n01`, independent compiler regression `c01` and `tests`. [summarize.py](summarize.py) validates normally installed/archive product bytes, exact helper and process-handle identity proof, marker/receipt snapshots, complete native transcripts, four matching raw-trace resource observations, retry build/source/profile identity and B checkpoints. It also retains native/Stop diagnostics and loaded core runtime paths.

[evidence-summary.json](evidence-summary.json) is **376,793 bytes**, SHA-256 `8605d5af4584614a2a592a92c51a6f0d6b0d788f0cb392c5d61f327ab53dd063`.

| Retained input | SHA-256 |
| --- | --- |
| `n01` local candidate ZIP | `4d28993abe3a2c40095821dea37f6188b0c657e00c1c9af369269fc3662053ab` |
| `c01` local candidate ZIP | `56db0d535f395652dac57fd455b53ad72db6017d781211dcd35b6c3b32326a94` |
| Shared content build ID | `ca87343ef473a11fec0c63bec23e830da2db5ec4f0fabdf5d1d205ed24cc970e` |
| Unit source/attempt manifest | `474e6967e099cf5efc03759b0e937bcefe7282495ff31047be5b7be9ae07edb7` |

The unit manifest retains all **47** tracked or new unignored `scripts/variant` source byte copies with pre-run hashes, final verification time, exact argv, complete results/logs and verification-runtime hashes. The collector checks the complete source-path set and both historical/current bytes. The PowerShell helper is bound separately by current/prepared/executed hashes. Retry log slices retain exact UTF-16 boundaries, prefix/tail hashes and JSON-quoted process arguments.

## Reproduction

Use two PowerShell terminals and choose a fresh short artifact name. From the repository root, prepare and launch the isolated control in the first terminal:

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/adapter-loss-2026-11-08'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n02' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario native-adapter-loss --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

While that isolated launcher is running, invoke its prepared helper in the second terminal. It waits for the exact nonce-owned readiness marker and refuses an existing receipt:

```powershell
$work = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\adapter-loss-2026-11-08\n02'
& (Join-Path $work 'driver/adapter-loss.ps1') -WorkDir $work
```

For the separate compiler regression, prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3`, then run only the ordinary launcher. Keep every attempted profile. Regenerate the summary without opening an editor or rerunning suites:

```powershell
& $python -B docs/research/adapter-loss-2026-11-08/summarize.py `
  --run (Join-Path $artifactRoot 'n01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

This local command-API slice adds no calibrated latency budget or release qualification. Native macOS, physical F5/menu, notification UI, certificate/trust/UI cancellation, arbitrary extension-host loss, descendants and the full repeated qualification matrix remain outside it. The source audit also confirms that current product cleanup trusts matching editor termination; this run's independent process observations do not turn that event into a general proof of debuggee exit.
