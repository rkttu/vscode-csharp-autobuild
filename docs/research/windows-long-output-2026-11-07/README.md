# Windows long output allocation

The repaired local candidate passes real Web build/debug/cleanup under the same **248-character output-name case** that failed before SDK build in the original installed control. This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) repair keeps ordinary paths and the existing recovery format: normal `mkdtemp` remains unchanged, while Windows `ENAMETOOLONG` can use exclusive directory creation with a secure six-character alphanumeric suffix. It does not move output into a different storage location or classify unknown output as terminal.

## Mechanism and ownership

The fallback uses nonrecursive `mkdir` with mode `0700`, retries only `EEXIST` for at most eight candidates, and returns only a directory it successfully created. Colliding paths are never reused or deleted. Other errors remain failures. Output registration and the existing cancellation checkpoint still precede build work, so the normal owned cleanup path applies. The v1 recovery schema, physical-path guards, scan budget and `run-[A-Za-z0-9]{6}` name contract remain unchanged.

The fallback emits `Created Windows file-app output after mkdtemp ENAMETOOLONG: <directory>` only after confirmed creation. A logging failure cannot turn a created directory into an untracked failure.

## Retained original failure

The original normally installed control is `validation-artifacts/web-profile-failure-retry-2026-11-07/installed-web-profile-failure-01`. Initial A-0 returned `false` during `Preparing build output` with `ENAMETOOLONG` from `fs.promises.mkdtemp`. No SDK build or intended Web-profile failure had begun. Its exact failed template contains 248 characters, with a 237-character parent. Those are observations under the pinned runtime, not a universal Windows threshold.

The historical candidate's five product modules are checked against Git base `9caef5773991a8bad468d7588297ade1f6585857` independently of the new runtime. Original result, candidate ZIP, installed module bytes, prepared harness and error log remain retained; the failure is not relabelled as a pass.

## Native filesystem observations

The same mechanism was measured using cached Node `24.22.1` and the pinned VSCodium executable in `ELECTRON_RUN_AS_NODE=1` mode: Node `24.21.0`, Electron `43.7.7`, libuv `1.52.1`, native ARM64.

| Exact observed operation at the 248-character output case | Both runtimes |
| --- | --- |
| Ordinary `mkdtemp` | `ENAMETOOLONG` |
| Namespaced `mkdtemp` | Creates output, but its returned namespace spelling fails the existing ordinary-base ownership containment check |
| Ordinary exclusive `mkdir` | Creates the eligible six-character output; file write/read/removal and ordinary-path containment pass |
| Existing v1 terminal recovery on ordinary long output | One receipt published and removed; both queues empty; unmarked and external guard bytes unchanged |

The recovery probe uses a writer and a distinct reader controller in the same process for each runtime. It is not a cold process, editor-host crash or SDK/debugger control. Probe sources and results are byte-identical post-run mirrors in the artifact root's `native-probes/`; original evidence and guard files remain at their recorded original paths. [probe.cjs](probe.cjs) and [recovery-probe.cjs](recovery-probe.cjs) are inspection copies of the executed source, not claims that those copies were launched from this research directory. Their original commands and dependencies are retained in the native manifest.

## Final validation

The normally installed native Windows ARM64 VSCodium control `l01-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` passes in **26.17 seconds** with the unchanged `web-profile-failure-retry` harness. It observes exactly five directory-attributed fallback lines: initial A, independent B, the intended Web-profile-rejected attempt, and two corrected A launches. Every allocated output uses the ordinary `base/<24hex>/run-<6alnum>` spelling and has 248 characters.

The actual SDK builds and native debugger reach A's breakpoint/evaluation and four successful HTTP sessions. The intended bad Web-profile root still returns `false` before handoff, with post-return output/queue/port cleanup while B survives the selected checkpoints. Correcting the profile and dirty revision yields three `true` callers sharing one new build/session. Final A/B Stops observe matching editor termination, captured PID exit, port reuse, output absence and empty terminal queues. A separate short-profile compiler-failure/concurrent-retry control `c01` passes in **24.11 seconds**, with **zero fallback lines**.

| Final identity | Value |
| --- | --- |
| Runtime SHA-256 | `fd72cad8a4c27ff707dec3c243db2b9cb7cae47fb64ce738a02e14731aebc1d8` |
| Long-control candidate ZIP | `13c237b0c178eaa06105f6e639807d05a40d51dc3948fa918202f41468bcf1f3` |
| Short-regression candidate ZIP | `31d9ca61f26874eff5c047363da5e67dc98c5bbda20fd10b73ff864fc1907e97` |
| Shared content build ID | `353e173623d71992a0af4189c0b428c0a1966cb4b4e0f1932106206f588a865b` |

Only `runtime.cjs` changes among the five product modules. [summarize.py](summarize.py) validates current/ZIP/installed byte identity for final candidates and Git-base/ZIP/installed identity separately for the historical failure. It also checks the exact executed unchanged harness, native probe mirrors and retained guard bytes, log/profile/source slices, all five long fallback paths, and the short control's ordinary allocation behavior. [The compact summary](evidence-summary.json) retains these bindings and observations; distinct ZIP digests are not treated as the same archive.

Identical final native functional test bytes reproduce `ENAMETOOLONG` with the old runtime (**one failure**) and pass with the repair (**one pass**). That case uses the real Windows filesystem and mocked SDK/editor APIs; the installed control separately supplies actual SDK/debugger evidence. Final strict Node **227/227** passes with no skipped/cancelled cases, and Python **39/39** passes. Added contracts cover ordinary behavior, Windows/error gating, exclusive collisions, bounded retries, noncollision errors, privacy options, diagnostic failure and disposal reentrancy.

The preparatory native long-storage test initially observed source-path disappearance before the queued deletion finished: nine focused cases passed and one queue-empty assertion failed. The corrected focused run passed ten cases; final test assertions wait for the runtime disposal drain. These are separate from the old runtime's allocation failure. The original preliminary test bytes were not separately captured: the manifest labels their source copies as post-run reconstructions of documented edits, not pre-run snapshots. It also records initial artifact/verification-runner setup failures before test subprocesses; the first CRLF matcher runner is retained as `verify-initial.py`.

## Regenerate retained evidence

Run from the repository root without launching an editor or repeating tests:

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifacts = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\windows-long-output-2026-11-07'
$previous = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\web-profile-failure-retry-2026-11-07'
& $python -B docs/research/windows-long-output-2026-11-07/summarize.py `
  --run (Join-Path $artifacts 'l01-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx') `
  --compiler-regression (Join-Path $artifacts 'c01') `
  --baseline (Join-Path $previous 'installed-web-profile-failure-01') `
  --native-probes (Join-Path $artifacts 'native-probes') `
  --tests (Join-Path $artifacts 'tests')
```

Final identities are exact byte bindings, including checkout newline conventions. Fresh runs record their own candidate ZIP digest and build identity; unchanged source inputs can retain the same build identity even when the ZIP digest differs.

## Fresh installed long-profile control

With the exact artifact root above, the following fresh 38-character profile name recreates the observed output length. A different workspace root changes that length. Preserve the retained original failure rather than reusing its attempted directory.

```powershell
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$editor = 'C:\Users\rkttu\AppData\Local\Programs\VSCodium'
$fresh = Join-Path $artifacts 'l02-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix (Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix') `
  --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix (Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix') `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor (Join-Path $editor 'VSCodium.exe') --editor-cli (Join-Path $editor 'bin/codium.cmd') `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --work-dir $fresh --cycles 3 --scenario web-profile-failure-retry
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed; preserve the fresh directory' }
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $fresh
```

## Scope

These controls do not qualify arbitrary path lengths, UNC/network storage, malicious filesystem replacement, physical F5/menu, macOS, certificate trust/cancellation, active-host loss, descendants or a release gate. Safety timeouts and individual measured samples are not calibrated latency budgets. Existing ownership uncertainty continues to preserve output.
