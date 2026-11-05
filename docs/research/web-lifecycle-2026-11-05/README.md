# Installed VSCodium Web lifecycle control

On November 5, 2026, a local candidate passed the real installed-command Web lifecycle scenario in native Windows ARM64 VSCodium. The final harness ran three A launch/Stop cycles while a separate B Web session remained active, then stopped B. The editor and launcher exited with code 0. This supplies bounded local evidence for [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) and a reusable starting point for [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15).

The [compact evidence](evidence-summary.json) retains four editor controls, exact input/loaded-module/harness hashes, local raw-artifact hashes, installation metadata, session ownership, HTTP responses, lifecycle observations and diagnostics. `run-02` passed before the additive provenance assertions and `run-03` passed with them. `run-04` passed the editor scenario but failed an external environment-restoration check. `run-05` passes both and is the final harness baseline: one fresh profile and three A cycles. Historical rows retain their original harness identities and evidence; the controls do not meet the stability contract's ten-cycle/two-profile qualification protocol.

## What was exercised

The [preparer](../../../scripts/variant/lifecycle/prepare.py) repackages a hash-pinned public 11.7.18004 VSIX using the current five repository-owned modules, a local display name and local candidate metadata. All 736 other ZIP payload entries, including upstream C# and native debugger bytes, are compared with the base and remain unchanged. The [launcher](../../../scripts/variant/lifecycle/run.ps1) normally installs both the pinned runtime dependency and the candidate with the VSCodium CLI into a dedicated extension directory. Only the separate empty [driver](../../../scripts/variant/lifecycle/driver.cjs) is passed through `--extensionDevelopmentPath`; target activation and command registration come from the installed extension.

The [test](../../../scripts/variant/lifecycle/extension-test.cjs) calls `netcoredbg.debugActiveFile`. It verifies the installed path, installer metadata, local candidate identity, all five module hashes and dependency path/version. A and B use the same [Slim Web fixture](../../../scripts/variant/lifecycle/fixtures/web.cs), distinct random launch tokens and explicit loopback HTTP profiles with browser launch disabled. No certificate trust action is required.

1. A reaches the source breakpoint at `marker += 2;`, evaluates `marker` as `40`, continues and serves `{pid, nonce, revision, value:42}`.
2. B starts independently and serves its own PID/token. A is stopped through its captured exact session object.
3. The test separately waits for A's matching editor termination event, captured PID disappearance, successful rebinding of its HTTP port, and disappearance of its owned output with empty terminal recovery queues. B must retain its session, PID, DLL/output and identical HTTP response.
4. A's source is edited without saving to `retry-1`, then `retry-2`. The installed command saves and rebuilds it. Each retry uses a fresh output directory, a new token/PID and the original A port; its HTTP response must contain the new revision.
5. After the third A Stop and B preservation check, B is stopped and the same owned-resource checks are applied.

The test records exact token-matched sessions and never uses the active-session selection to choose a Stop target. Failure cleanup requests Stop only for those sessions. A fallback HTTP shutdown requires a prior exact nonce/PID match and calls the fixture's `StopApplication`; it does not kill arbitrary processes or delete output paths. An exclusive attempt marker rejects reuse of an attempted profile. A separate duplicate-attempt check confirmed rejection and preserved all 13 checked result/state/trace/installation/editor/SDK/stdout/stderr files. The final launcher also retries a racing state snapshot read and guards an unavailable editor command line before its own-process deadline fallback.

## Recorded inputs

| Input | Recorded value |
| --- | --- |
| OS | Windows build `26300.9711`, registry DisplayVersion `26H2` |
| VSCodium | `1.143.17232`, commit `c072cf642cbbadabefa22f39c58cc902a8b7427f`, native ARM64; extension API version `1.143.1` |
| Editor executable SHA-256 | `61b273b2c0196d7cee4ba84f7412ccc74975f0fcefd3579e69a7b373f79027cd` |
| SDK | `10.0.403`, `C:\Program Files\dotnet\dotnet.exe`; observed debuggee Core runtime module directory `Microsoft.NETCore.App\10.0.14` |
| Runtime extension | `ms-dotnettools.vscode-dotnet-runtime` `3.2.0`; VSIX SHA-256 `a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541` |
| Base VSIX SHA-256 | `0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5` |
| Final local VSIX SHA-256 | `338d86097df5579fcb6c566431417a7e118ec765d79eed0cf8e4b657581be54d` |
| Local content build ID | `017eae63f14d8f5aa4e67eedf843448c079d006e52e4c372a2f33aec48b8c2f2` |
| Preparation checkout HEAD | `4d4ca0ac1ff6a1e98872e473b41ce565ed3148a4` |
| Supporting tools | Node `24.22.1 win32 arm64`, Python `3.12.14` |

The source commit records checkout HEAD at preparation time. Exact module and harness hashes identify the local additions used before their later commit. The loaded final extension directory is `run-05/extensions/dotnetdev-kr-custom.csharp-with-netcoredbg-11.7.18004` under the isolated artifact root. Installer metadata reports `targetPlatform: "undefined"`; native target evidence comes from the editor PE check, extension host `win32-arm64`, candidate target, preserved native input and successful real debugging, not that metadata field. Full loaded-path/build/installer metadata is retained in the summary.

The candidate keeps version `11.7.18004` and uses `C# (netcoredbg) LOCAL WEB LIFECYCLE TEST` as its display name. It is a local-only repackaging, not a publication, an extension update test, or a verification of newly released bytes. The summary records each VSIX hash separately. All controls share the same owned-module hashes and unchanged-payload digest; build IDs also include the preparation checkout HEAD.

## Final run observations

Elapsed time for `run-05` was about 20.57 seconds. These are observed milliseconds after each targeted Stop request, not product latency budgets or exact process-death timestamps. PID/output checks poll, and the timestamps show first successful observations.

| Launch | Stop Promise resolves | Matching editor termination | PID observed gone | Port rebind succeeds | Output and queues clear |
| --- | ---: | ---: | ---: | ---: | ---: |
| A initial | 37.211 | 665.659 | 696.707 | 698.101 | 698.342 |
| A retry-1 | 42.589 | 637.372 | 658.586 | 659.434 | 659.579 |
| A retry-2 | 37.754 | 694.275 | 718.436 | 719.519 | 719.697 |
| B final | 42.805 | 620.552 | 638.112 | 639.158 | 639.356 |

Stop Promise completion preceded the matching editor event in each case. This does not establish that a process remained alive throughout that interval. The PID, port and output assertions provide separate evidence; a resolved Stop Promise alone is not the cleanup assertion. B preserved the same PID/token/response and output after each A cycle.

The logs are not error-free. The final control reports `Error: read error` once per adapter after its Stop request, four times total. A retry-1 and retry-2 also receive one failed `threads` response each with `0x80004005` during Stop. The summary retains diagnostics from all four controls with exact messages, sessions and relative times, and the hashed raw stderr/trace remain local. The pass criterion is the stated behavioral lifecycle assertions. These observations are not classified here as harmless, fixed or a complete explanation of adapter shutdown; diagnostic classification remains follow-up work.

## First failures and validation

`run-01` failed during candidate preparation before an editor was launched. Reusing a source `ZipInfo` object for output mutated its header offsets, breaking later reads used by the unchanged-payload comparison. `copy.copy(info)` fixes that sharing, and the preparation regression checks both original bytes and candidate payload preservation. The partial candidate is retained with its hash; the original traceback was visible in tool output but was not saved as a raw file.

The initial unsafe-backslash negative unit case also failed: Python's Windows ZIP handling normalized the name before filename-based validation. The preparer now validates `orig_filename`, and the fixture models the raw backslash spelling. These were preparation/test-tool defects, not failed editor cycles, and the later passing controls do not erase them.

Validation also passed the strict Node suite (131 tests, no skips), Python helper suite (39 tests, including five lifecycle preparation cases), Node syntax checks and PowerShell parse check. The five new cases cover payload preservation, pinned input/target rejection, duplicate/path-escape rejection, preservation of existing results, and native PE target parsing with truncated-header diagnostics. These checks supplement the real editor result.

Review follow-up renames the editor profile variable to avoid PowerShell's automatic `$PROFILE`, validates short PE reads before unpacking, restores the caller's 16 affected process environment variables in an outer `finally`, and retains the original `firstFailure` if a later callback fails during cleanup. The first callback error is recorded separately. No production runtime code changes are included.

`run-04` passed the editor scenario, but its external caller-environment check failed: an initially absent variable was restored as an empty value. That follow-up failure is retained in `run-04/external-review-check.json`. The restoration now passes an explicit typed null for absent values; the later editor pass alone does not erase this failure.

The final external check passes all 16 environment variables, including initially absent, empty and nonempty values, and confirms `$PROFILE` is unchanged. It also rejects reuse of `run-05` with all 13 checked evidence files unchanged. Both the failed check and final passing check are hashed and retained in the summary.

## Local reproduction

Run from a checkout containing this change on native Windows ARM64 with the exact VSCodium and .NET SDK above. The preparer currently enforces this Windows ARM64 baseline. Supply the hash-matched public base VSIX at `validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix`. Supply the pinned runtime dependency under `validation-artifacts/web-lifecycle-2026-11-05/resources/`; its recorded download URL is `https://open-vsx.org/api/ms-dotnettools/vscode-dotnet-runtime/3.2.0/file/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix`.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/web-lifecycle-2026-11-05'
$work = Join-Path $artifactRoot 'run-06' # must be new; retain earlier attempts
& $python scripts/variant/lifecycle/prepare.py `
  --base-vsix 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix' `
  --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix (Join-Path $artifactRoot 'resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix') `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --work-dir $work --cycles 3
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

The launcher uses dedicated profile, extensions, APPDATA/LOCALAPPDATA, temporary, .NET CLI home and NuGet directories, disables editor/extension updates, and pins SDK selection with `global.json`. It restores the affected process environment on return, including on failure. It clears package sources for this package-free fixture. Existing user editor profiles are not the test target. The 90-second phase limits and 300-second editor limit are safety limits, not calibrated qualification budgets. Preserve a failed work directory and choose a new directory for another attempt.

Raw local evidence remains in `validation-artifacts/web-lifecycle-2026-11-05/run-02/` through `run-05/`: `result.json`, `expected.json`, `trace.jsonl`, `launcher-result.json`, state/launch/attempt metadata, install/version/stdout/stderr logs and editor output logs. The compact summary hashes these files; large VSIX files and full traces are not added to the repository.

To regenerate the summary from the original local artifact layout, run:

```powershell
& $python docs/research/web-lifecycle-2026-11-05/summarize.py `
  --runs (Join-Path $artifactRoot 'run-02') (Join-Path $artifactRoot 'run-03') (Join-Path $artifactRoot 'run-04') (Join-Path $artifactRoot 'run-05') `
  --failed-preparation-dir (Join-Path $artifactRoot 'run-01') `
  --duplicate-attempt-check (Join-Path $artifactRoot 'duplicate-attempt-check.json') `
  --dependency-download (Join-Path $artifactRoot 'resources/runtime-download.json') `
  --review-followup-failure (Join-Path $artifactRoot 'run-04/external-review-check.json') `
  --review-followup-check (Join-Path $artifactRoot 'review-followup-check.json')
```

This covers command API invocation, direct Web debuggees, ordinary targeted Stop and same-window dirty-source retry. It does not cover physical F5/menu input, macOS, cancellation, host reload/crash, spawned grandchildren, forced cleanup failure, power-loss recovery or the full [stability qualification protocol](../../stability-contract.md). Those remain separate evidence and implementation work; #18 stays open.
