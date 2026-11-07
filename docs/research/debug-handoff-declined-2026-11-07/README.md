# Installed editor-declined handoff and same-file retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up checks the existing rejected-start boundary in a normally installed VSCodium extension. The optional `debug-handoff-declined-retry` scenario injects an exact-token editor configuration rejection after a real successful build and Web preparation. The five product modules remain unchanged from merged [PR #38](https://github.com/rkttu/vscode-csharp-autobuild/pull/38), commit `9c2756eb4ac15f72053e11fb9c57ef750f36592e`; no package is published.

The intended control `h01` passes in **27.29 seconds** on native Windows ARM64 VSCodium `1.143.17232` (API `1.143.1`), SDK `10.0.403`, with editor exit 0. Independent compiler-error regression `c01` passes in **30.54 seconds**, also with exit 0. Final strict Node **228/228** and Python **39/39** checks pass; no intended Node case is failed, skipped or cancelled. Neither installed-editor attempt has an unexpected failure.

The first Node invocation mistakenly included two upstream integration wrappers without their required CLI argument. All 228 intended file-app tests passed, while those two wrappers failed with `ERR_INVALID_ARG_TYPE` (exit 1). The exact argv, complete log and result remain retained separately. The corrected invocation selected the intended five suites; no source change was made between invocations. This was a test-runner selection error.

## Mechanism and observations

1. Normally install the local candidate and pinned runtime dependency into a fresh isolated profile. Launch independent A and B Web sessions through the public command API, verify their distinct HTTP token/PID ownership, and exercise A's source breakpoint/evaluation. Stop A and wait for its exact editor termination, PID exit, reusable HTTP port and output/queue cleanup.
2. Keep the valid saved A source and write a valid HTTP profile with a fresh token. Register a test-only `coreclr` configuration provider that passes other tokens through and returns `undefined` for this exact failed token. The [official DebugConfigurationProvider contract](https://code.visualstudio.com/api/references/vscode-api#DebugConfigurationProvider) defines `undefined` as preventing startup; `null` additionally opens configuration UI. Provider chains have unspecified relative order, so this control makes no claim about ordering against other providers.
3. Invoke the public command three times concurrently. One real SDK build and successful Web preparation reach one callback. At that callback, retain the generated configuration and exact DLL/PDB path, positive byte count and SHA-256 while the files exist. The actual editor declines startup, all callers return `[false, false, false]`, and the exact runtime diagnostic identifies `Starting netcoredbg` as failed.
4. Require no new failed-token adapter tracker, API session or DAP process event, then sample the failed output absent, both terminal queues empty and A's port reusable after command return and log flush. Check that B retains its exact session, PID, token, HTTP response and output.
5. Dispose the provider in `finally` before retry. Make a valid dirty A revision edit and invoke three concurrent commands: `[true, true, true]` shares one saved build, one session and fresh output. Check B again, finish three A Stop cycles, then stop and clean B.

The rejection is **test-injected through the actual editor provider API**. It does not reproduce a native adapter executable/process failure or inject the product runtime. The valid source/profile are unchanged across the failure; the retry disables the test provider and uses a new source revision and ownership token. DLL/PDB artifact bytes are removed by normal owned cleanup; only callback-time metadata is retained. Empty failed-token captures describe the observed handoff, not global OS-process absence.

The strengthened runtime unit covers three coalesced failed callers and three successful retry callers while the earlier error-notification promise stays unresolved. Its CLI/editor inputs are mocked. The installed control does not measure notification-toast visibility or user dismissal.

## Retained evidence

Raw candidate profiles and logs remain under `validation-artifacts/debug-handoff-declined-2026-11-07/`, using `h01`, independent compiler regression `c01` and final `tests`. [summarize.py](summarize.py) reuses the existing Web lifecycle/compiler validators and adds this provider contract. [evidence-summary.json](evidence-summary.json) binds unchanged product bytes at the Git base, current/ZIP/normally installed module bytes, candidate identity, loaded extension path, native editor/SDK/runtime-dependency inputs, executed harness, exact UTF-16 log slices and JSON-quoted arguments, source/profile/configuration observations, provider lifecycle and discrete B checkpoints.

The summary is **99,916 bytes**, SHA-256 `9d447bce2f6d9fb48f94268b215e468851598d45b0a5e4b9b0e4d6d02938bbcc`.

| Retained input | SHA-256 |
| --- | --- |
| `h01` local candidate ZIP | `eb569a6eff12798000fb22cf8f4078a7e6e5edb10a6bb498c823a31bc1896c44` |
| `c01` local candidate ZIP | `d06ef048ce4a2bf01e2bf5459c0284e2f7e1447ab44700eb7137a55ac9edae65` |
| Shared content build ID | `5d580021bf1e78e5342f7ddc9a91fed5de04abc4a8578b82932d500b9407603f` |
| Unit source/attempt manifest | `0f8814ab35eea5e626add311891c140d3eea98862edd9713b6ba322d8e308972` |

The unit manifest records pre-run hashes for 46 source files, a final source-verification timestamp, exact argv and result for every invocation, raw logs and verification-runtime hashes. The collector rechecks every current source against those hashes; separate historical source-byte copies are not retained. Unexpected native attempts, if any, remain separate and must be passed with `--failed-runs`.

## Reproduction

Run from the repository root with the pinned native editor, SDK and original VSIX inputs. Choose a fresh short artifact name and preserve each attempted profile.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/debug-handoff-declined-2026-11-07'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n01' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario debug-handoff-declined-retry --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

For the separate compiler regression, prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3`, then use the same launcher. The launcher restores its process environment and refuses a reused attempt. The test provider belongs to the isolated driver and is disposed in its local `finally` and run-level cleanup.

Regenerate the summary without relaunching an editor or rerunning suites:

```powershell
& $python -B docs/research/debug-handoff-declined-2026-11-07/summarize.py `
  --run (Join-Path $artifactRoot 'h01') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests')
```

These local command-API profiles use discrete liveness/resource samples and provide no release qualification or latency budget. Native macOS, physical F5/menu, notification UI, certificate/trust/UI cancellation, arbitrary active-host loss, descendants and the full repeated qualification matrix remain outside this slice. Stop-time adapter diagnostics remain retained alongside the behavioral assertions.
