# Installed SDK-selection failure and corrected retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up verifies the existing SDK-check failure boundary and correction in the same installed editor window. It adds the optional `sdk-selection-failure-retry` scenario and one focused runtime test. The five product modules remain unchanged from merged [PR #37](https://github.com/rkttu/vscode-csharp-autobuild/pull/37), commit `da4b41e736fd73af00ca531f7bff3f0452563c44`; no package is published.

The intended control `g01` passes in **21.62 seconds** on native Windows ARM64 VSCodium `1.143.17232` (API `1.143.1`), SDK `10.0.403`, with editor exit 0. Independent compiler-error regression `c01` passes in **26.87 seconds**, also with exit 0. Final strict Node **228/228** and Python **39/39** checks pass; no Node case is failed, skipped or cancelled. There was no failing test or native attempt in this slice. The new unit test uses mocked CLI/editor inputs and verifies failure cleanup plus correction while the earlier error notification stays unresolved; the installed control supplies the actual SDK diagnostics.

## Scenario and observations

1. Normally install the local candidate and pinned runtime dependency into a fresh isolated profile. Launch A and B through the registered command, verify real HTTP responses with distinct PID/token ownership, and exercise A's breakpoint/evaluation.
2. Stop A while B continues. Retain exact saved A source/profile, original workspace `global.json`, and known A output-parent contents. Use the native `dotnet --list-sdks` inventory captured by the launcher before editor startup: it contains `10.0.403` and excludes requested `99.0.100`. Change only the isolated `global.json` to SDK `99.0.100` with `rollForward: disable`.
3. Invoke the command. It returns `false` during `Checking .NET SDK`, with native `A compatible .NET SDK was not found.` and `Requested SDK version: 99.0.100` diagnostics. The exact output slice contains one `dotnet "--version"`, no `--info` or build, and no allocation, Web-preparation or handoff phase. There is no new failed-request adapter creation/API session/DAP process event.
4. Require A source/profile and ambient SDK root to remain unchanged, output-parent entries `[] → []`, both terminal queues empty, and A's HTTP port reusable. B retains its exact session, PID, nonce, HTTP body and output at the selected checkpoints.
5. Restore the original `global.json` **bytes in `finally`** and verify its hash. Make a valid dirty A revision edit and invoke the command three times concurrently: `[true, true, true]` shares one saved build, one handoff/session and fresh output distinct from prior A. Check B again, finish three A Stop cycles, then stop and clean B.

SDK selection fails **before output allocation**. There is no failed `output` to identify or delete. Parent-directory and queue observations are post-return samples; the phase/log boundary supplies the pre-allocation observation. The failure reuses the unchanged profile's token after A-0 has stopped, so absence applies to **new captures for the failed request**, not to every historical event with that token. Empty failed-request captures do not prove global OS-process absence.

The failed source is byte-identical to the earlier actual successful Web source (`4d865a4bfb51e53379d0c73b306ad27ef7c925e192d2de3e9201f7acc4fd2cb6`). The original and restored SDK configuration both hash to `5bc559894f23e9573817cddfaa9801374148727d9e1f29f71b07689e2ea9fa77`; the invalid configuration hashes to `9cb27b85f62bf68b0ee2ddb5c48ae23506a26401ca59bf5d08997dd351284d7f`. Exact source/profile/configuration/inventory snapshots retain path, byte count, SHA-256 and base64.

## Evidence

Raw profiles, candidates and logs remain under `validation-artifacts/sdk-selection-failure-2026-11-07/`, using `g01`, `c01` and `tests`. [summarize.py](summarize.py) imports the existing Web lifecycle/compiler-failure validators and adds the SDK contract. [evidence-summary.json](evidence-summary.json) binds unchanged product bytes at the Git base, current/ZIP/normally installed module bytes, candidate build identity, loaded extension path, native editor/SDK/runtime-dependency inputs, frozen executed harness, exact UTF-16 log slices and JSON-quoted arguments, snapshots, selected B checkpoints and final cleanup.

The summary is 84,234 bytes, SHA-256 `796bbe0a3582dade3ebdcfa8b40813ce692803c1f7d0d292348161e0df711382`. Independent in-memory regeneration reproduces those exact bytes.

| Retained input | SHA-256 |
| --- | --- |
| `g01` local candidate ZIP | `d13264b4caecb02902ec20f2bba47a5cee6f082649291095e77d88449525d582` |
| `c01` local candidate ZIP | `9955c3cf26ff3f4c5cf450539ffe9962e6de3bb74c0e21894cfe83fa1405530a` |
| Shared content build ID | `585051b08111297cf66a8fbe3f46d235eb4f29e28501cf6f1cf3753139a1be63` |
| Native SDK inventory | `760573622f5202049060d7c11f57124e44d28beb23df734bb8ea3b81a1cb866b` |
| Unit verification manifest | `aa6a781f7a2999e68d04ef256908e485ba0fa5a50a6feb854ed31b061955829e` |

The unit manifest records source snapshots captured before execution and confirms unchanged source bytes after both suites. The collector compares those copies with current source and checks raw log digests, exact counts and verification-runtime digests. The default compiler regression retains its real compiler failure/concurrent correction and does not enter the optional SDK branch or capture an SDK inventory. Unexpected editor failures, if any, must remain separate and be supplied with `--failed-runs`.

## Reproduction

Run from the repository root with the pinned native editor, SDK and original VSIX inputs. Use fresh, short artifact names; preserve every attempted profile.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/sdk-selection-failure-2026-11-07'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n01' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario sdk-selection-failure-retry --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

For the separate compiler regression, prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3`, then use the same launcher. The SDK fault changes only its owned workspace configuration and restores it in `finally`; it does not install/remove SDKs or change a global SDK configuration. The launcher restores its process environment and refuses a reused attempt.

Regenerate the retained summary without relaunching an editor or rerunning suites:

```powershell
& $python -B docs/research/sdk-selection-failure-2026-11-07/summarize.py `
  --run (Join-Path $artifactRoot 'g01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

## Limits

These are two local installed command-API profiles with discrete liveness/resource samples, not release qualification or a latency budget. No direct failed SDK child PID is sampled. Stop-time adapter diagnostics remain retained alongside behavioral assertions. Native macOS, physical F5/menu, certificate/trust/UI cancellation, arbitrary active-host loss, descendant processes and the full repeated/calibrated qualification matrix remain outside this slice.
