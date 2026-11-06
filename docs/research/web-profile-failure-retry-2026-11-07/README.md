# Installed Web-profile failure and corrected retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up verifies the existing late Web-profile guard after an actual successful build. It adds an optional `web-profile-failure-retry` installed-editor scenario and a focused runtime regression; the five product modules remain unchanged from merged [PR #35](https://github.com/rkttu/vscode-csharp-autobuild/pull/35), commit `0a837aebc153c2c51a93ad4a07efac102c11c8ee`.

The intended scenario passes in fresh profile `w02` on native Windows ARM64 VSCodium `1.143.17232` (API `1.143.1`), SDK `10.0.403`, in 27.60 seconds. The earlier, longer-profile attempt failed before the intended scenario with `ENAMETOOLONG`; that separate Windows path-length limitation remains recorded below. Final strict Node **217/217** and Python **39/39** checks pass, with zero skipped/cancelled Node cases. The new runtime test verifies the already-existing guard's cleanup and same-file correction while its earlier notification stays pending; this is added coverage, not a claim of a newly repaired product defect.

## Scenario

1. Normally install the local candidate and pinned runtime dependency into a fresh Windows ARM64 VSCodium profile. Launch independent A/B HTTP fixtures with distinct tokens, ports and PIDs, and check A's real breakpoint/evaluation.
2. Stop A and leave B live. Keep A's saved, previously successful source byte-identical. Change only A's HTTP `.run.json` profile to supply a wrong `DOTNET_ROOT` under the isolated artifact directory. The ambient SDK root remains unchanged.
3. Run the registered command. Require one successful actual build followed by the exact profile-root error during `Preparing web launch settings`, before `Starting netcoredbg`. Require `false`, no token-matched adapter creation/API session/DAP process event, the exact logged output absent, both terminal queues empty and the A port reusable. Check B's same PID/token/response/output again.
4. Remove the bad profile root, change only A's valid revision with a dirty editor edit, and invoke the command three times concurrently. Require three `true` results sharing one build, one session and fresh output serving the corrected revision. Check B again, finish three A Stop/retry cycles, then stop and clean B.

The profile error is `The web launch profile DOTNET_ROOT does not identify the selected dotnet installation.` Exact failed/corrected profile and source snapshots retain path, byte count, SHA-256 and base64. The failure source matches the earlier real successful Web launch; it starts clean and remains unchanged, so this stage does not claim a source-save operation. The corrected retry exercises dirty-source saving.

## Validation and evidence

Results are retained under `validation-artifacts/web-profile-failure-retry-2026-11-07/`. The intended scenario uses `w02`; independent `c01` preserves the existing real compiler-error/concurrent-retry control. [summarize.py](summarize.py) imports the existing Web lifecycle/compiler-failure validators and adds the late-profile contract. [The compact summary](evidence-summary.json) binds exact current, ZIP and normally installed module bytes, unchanged product bytes at the merge base, candidate/build identity, native editor/SDK/dependency inputs, executed harness, log slices, snapshots and verification logs.

The collector reconstructs the driver's UTF-16 log offsets and exact JSON-quoted source/output arguments. It checks one successful build before the Web failure, no handoff phase, exact root diagnostics, post-return output/port sampling and discrete B checkpoints; corrected source/profile snapshots and the one-build/one-session retry are separately bound. Earlier failures, if any, stay in their original directories and are passed with `--failed-runs` rather than relabelled as successes.

The separate compiler-error regression `c01` also passes three A cycles and B final cleanup in 28.66 seconds, with editor exit 0. Its local ZIP SHA-256 is `87b19c8396f792db35f33d52ddcde2cb0d17d546efc60107a9153ebe5be7b2f8`; its content build ID and five product-module hashes match `w02`. The complete summary is 93,142 bytes, SHA-256 `c41329249dfa5b58a33d6a3c6dbc56b3787068ea940077e3ca71153bd6b21537`.

In `w02`, the clean failed-attempt source remains the exact earlier successful Web source (SHA-256 `4d865a4bfb51e53379d0c73b306ad27ef7c925e192d2de3e9201f7acc4fd2cb6`). Its command returns `false` after the completed build and the exact Web-root diagnostic; adapter/API-session counters are zero and no token-matched DAP process event is recorded. Correcting the profile and dirty revision yields `[true, true, true]`, one actual build/handoff and one fresh session. B is checked after each selected boundary, then all configured A/B Stops release their owned outputs and resources.

| Final intended-control input | Value |
| --- | --- |
| Local candidate ZIP SHA-256 | `96485fb45127065a380be0fa11a34e104a48a55c6c29d5f0551674938491b53d` |
| Content build ID | `a8f7c3d2a506ade2b8822525925714e1603aad359c6d5f2a677484555458baf1` |
| Failed profile SHA-256 | `0c9dc67b61774db55fb3c255a1ad8b872cb63681424dc3435c00023545dc5263` |
| Corrected first-retry profile SHA-256 | `50c724efc7d774030ceb3b9f6418182b355ef8f186e64f482b3b7d7e1bfa12ce` |

These observations are sampled after command return and log flushing: the failed command lasts 3295.927 ms, its output is first confirmed absent 1.111 ms after return, and the port rebind succeeds 2.199 ms after return. They do not identify the actual deletion instant or establish a performance budget.

## Retained first failure

`installed-web-profile-failure-01` exits with code 1 during initial A-0, before a real build or the selected Web-profile fault. The output records `Phase failed: Preparing build output` and `ENAMETOOLONG` from `fs.promises.mkdtemp` at the deeply nested custom isolated storage path ending in `file-based-apps/.../run-XXXXXX`. The command returns `false`; no token-matched session is captured. The five product-module bytes, content build ID and executed harness match the later controls; each run retains its distinct ZIP digest. The first result, log, candidate and input hashes remain intact; the collector rejects treating it as late-Web coverage or a passing run.

Fresh shorter sibling names `w02` and `c01` avoid this observed setup boundary without changing product or harness bytes. This does not repair or qualify long custom-profile paths. The Windows path-length limitation is an outstanding finding for #18, and a green shorter-path observation does not replace the original failure.

## Reproduction

Run from the repository root with native Windows ARM64 VSCodium `1.143.17232`, SDK `10.0.403`, and the original pinned public packaging base/runtime VSIX. Choose fresh directories and preserve every attempted profile.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/web-profile-failure-retry-2026-11-07'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n01' # must be new; keep the custom profile path short
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario web-profile-failure-retry --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

For the separate compiler regression, prepare another fresh directory using the same inputs with `--scenario build-failure-retry --cycles 3`, then use the same launcher. The launcher isolates profile, extension, NuGet/SDK and temporary paths, restores its process environment and refuses a reused attempt. No target runtime substitution, global SDK mutation, certificate commands, OS trust change or UI input is used by this scenario.

Regenerate the retained summary without relaunching an editor or rerunning suites:

```powershell
& $python -B docs/research/web-profile-failure-retry-2026-11-07/summarize.py `
  --run (Join-Path $artifactRoot 'w02') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests') `
  --failed-runs (Join-Path $artifactRoot 'installed-web-profile-failure-01')
```

## Limits

This is one local command-API scenario and a separate regression profile, not release qualification or a latency budget. No token-matched handoff event is a measured debugger boundary, not proof that no unrelated OS process exists. No SDK child PID is sampled here. Output/port checks follow command return and log flushing; their times do not establish the exact deletion-before-return ordering. B liveness is checked at separate observed points, not continuously. Stop-time adapter diagnostics remain retained alongside the behavioral assertions.

Native macOS, physical F5/menu, certificate/trust/UI cancellation, arbitrary active-host loss, descendant processes and the full repeated/calibrated qualification matrix remain outside this slice. No package is published.
