# Recover complete terminal staging after interrupted publication

This follow-up to [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) handles a terminal output that has already moved into a complete version-1 staging entry when its owner exits before the final publication rename. The previous recovery pass inspected only `terminal-cleanup-v1`. It therefore preserved a complete `terminal-cleanup-staging-v1` entry indefinitely after that interruption.

Recovery now also inspects complete staging entries, publishes eligible entries through the existing ready queue, and uses the same fixed `output` child deletion. The v1 record contains no caller-supplied deletion path. Both queues share the existing limit of 32 inspected entries and one eligible cleanup attempt per pass. Invalid or incomplete entries remain untouched.

## Actual native Node process boundary

The identical [driver](native-control.cjs) runs the actual product runtime and recovery module against a real filesystem. SDK selection/build results and VS Code API events are controlled. The owner first starts an independent stub session, then makes a second source's controlled build fail. A narrow `fs.promises.rename` hook waits until the source-to-staging move has completed and a full receipt and payload exist. It records that boundary and calls `process.exit(73)` **before executing the staging-to-ready publication rename**. No recursive deletion has started.

A second native Node process activates a fresh runtime and awaits its normal `recoveryReady` operation. Both cases execute the exact same `runtime.cjs` bytes from merged [#32](https://github.com/rkttu/vscode-csharp-autobuild/pull/32), commit `8681a7b6e46201fb29c87efd03ae1e418c5d28e9`. Their executed driver bytes are also identical. Only the executed recovery module changes; test-file snapshots are provenance rather than executed control code.

| Control | Interrupted / cold PID | Observed exits | Cold recovery | Complete staging payload |
| --- | --- | --- | --- | --- |
| Baseline `8681a7b6…` | `65056` / `55244` | `73` / `0` | scanned 0, attempted 0, removed 0 | Remains; old gap reproduced |
| Final recovery | `91692` / `80464` | `73` / `0` | scanned 2, attempted 1, removed 1 | Promoted and removed |

Baseline control success means the old gap was reproduced, **not** that its desired behavior passed. Its `desiredBehaviorObserved` value is false; the final control's value is true. Both first executed controls pass their expected conditions. Native executable/hash, complete staging receipt/payload hashes, subprocess commands and exits, synced traces, module snapshots and filesystem proofs are retained under `native-controls/`.

All seven guard files remain byte-identical in both cases: unmarked output, an external sentinel, an incomplete record-only staging entry, a malformed staging record and its payload, an independent active stub-session output, and a replacement recreated at the original source-output path after its move. Cold activation selects no SDK, starts no debug session and sends no Stop. The replacement proof covers recreation after the confirmed source move.

This is a real native Windows ARM64 Node-process exit and a new process with controlled SDK/editor APIs. Actual installed-editor evidence is recorded separately. This control does not establish actual debuggee lifetime, editor reload, macOS behavior or recovery of incomplete/ambiguous staging.

## Normally installed extension-host interruption

A separate first-attempt control, `installed-publication-01`, normally installs the local candidate and pinned runtime dependency in native Windows ARM64 VSCodium. Only a separate test driver uses a development path. The public command builds and starts an actual Web app through the SDK/native debugger. After matching session termination, captured debuggee PID exit and port reuse, the exact publication-rename hook confirms a complete staged receipt plus intact DLL/PDB/sentinel hashes. It exits the extension host before invoking the final staging-to-ready rename; this is **not a partial-delete injection**.

Native process inspection ties extension host **88140** to isolated editor process **91812**, retaining executable, profile command line and creation times. VSCodium's own `main.log` records host exit code **73**, and the first app exits naturally with code 73. An explicit second app launch reuses the profile; its new extension host **92760** recovers the staged terminal entry. It preserves a valid record-only stage, an unsupported-version stage and its output, unmarked/external sentinels and a replacement at the original run path. All six sentinel files remain unchanged after both apps exit.

The second launch also performs a real public-command retry, verifies its HTTP PID/nonce/value and then releases its exact PID, port and fresh output. There are no failed actual editor executions or superseded preparations in this slice.

| Observation | Recorded value |
| --- | --- |
| First editor / extension host | `91812` / `88140`, observed natural exit 73 |
| First debuggee PID / port before interruption | `89448` / `53292`, confirmed exited / reusable |
| Explicit second editor / new extension host | `66988` / `92760`, final app exit 0 |
| Retry debuggee PID / port | `41212` / `57979`, confirmed exited / reusable |
| Local candidate SHA-256 | `860c91caaa2d52b4fd9b38c295d4197012ceb9845fdb07bd7896d0901c3cce26` |
| Local build ID | `780e04c5acdc25e682d77771bc9aedc7c8c56352ae8bcae520eb5d290cd485c7` |

This verifies one confirmed-terminal, complete-staging interruption and explicit subsequent app activation. It does not qualify automatic Reload, active-session host loss, a source move whose identity cannot be confirmed, filesystem power loss, descendant processes or native macOS behavior. Existing offline language-service restore warnings remain outside these cleanup controls.

## Ownership and eligibility

Only a valid v1 receipt together with a real staged `output` directory is eligible. Record-only, output-only, malformed, extra-content and redirected entries remain untouched. A UUID present in both queues is treated as a conflict; neither payload is overwritten. Existing physical-path, file-size and record-schema validation still applies.

The original owner tracks whether its source move is confirmed. After that confirmation, it retires the old pathname and can reconcile another host's publication/removal without reopening a replacement at the old path. A late source-move error can be confirmed by the staged directory identity. If that identity is already unavailable, the original failure and ownership remain conservative rather than inferring success or deleting a replacement.

The bounded pass remains one attempt, including a failed publication. This does not add queue fairness, I/O wall-clock deadlines, power-loss durability or protection against arbitrary malicious same-user filesystem replacement.

## Automated regressions

Eight focused regressions run with identical final test bytes against both recovery implementations: all eight fail the baseline and pass the final implementation. The full strict Node suite passes **171 tests with zero skips**; the Python helpers pass **39 tests**. The added checks cover complete-stage recovery, paused/late owner reconciliation, confirmed and ambiguous source moves, the shared scan limit, failed promotion accounting and concurrent promoters/removers. The full suite also covers incomplete/malformed entries, duplicate UUIDs, original failure preservation and native junction/symlink guards.

Earlier six/eight-case snapshots and the initial full run remain retained with their own identities. Two preexisting expectations described the old staging-preservation behavior and the old late-ready-error behavior; they were updated for the explicit new semantics while retaining payload and ownership checks. Final focused raw outputs are `tests/before-final.txt` and `after-final.txt`; the final full output is `tests/full-final.txt`.

Normally installed VSCodium `installed-regression-01` also passes in **29.11 seconds** on the final source. It covers a real breakpoint/evaluation, actual CS0103 build failure, a dirty correction with three concurrent callers sharing one fresh build/session, three A Stop/retry cycles and exact B PID/nonce/output preservation followed by B cleanup. Its candidate SHA-256 is `193423dbb6786f48454e2499ee447a324414bdf4c0d41d4e623f865ced6ffb89`; its build ID matches the publication-interruption candidate. The different ZIP hashes are retained individually.

Final recovery SHA-256 is `099f74d6d25c0fad95b0f56e3adaebe43a3f211991b6ef436f92ceed6be199d4`; final recovery-test SHA-256 is `f26a5aa152ccbb0ea2c217e3ecd4d115f9dbe06bed9fa08b1e0e4c9b3e0caa96`. The native controls both execute the Git snapshot of unchanged runtime (`664f0dee…8a9`, LF); the normally installed candidate uses the unchanged working-tree runtime (`8b6c702…ffa2`, CRLF). This is the same runtime source, with the different raw byte identities kept explicit.

## Reproduction

Use a fresh work directory for every executed control and preserve the first result. The following two runs pin the same runtime to `8681a7b6…` while selecting old and current recovery code.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/complete-staging-recovery-2026-11-06'
& $python -B docs/research/complete-staging-recovery-2026-11-06/run-native-control.py `
  --node $node --work-dir (Join-Path $artifactRoot 'native-controls/baseline-new') `
  --recovery-ref 8681a7b6e46201fb29c87efd03ae1e418c5d28e9 --expect-recovered no
& $python -B docs/research/complete-staging-recovery-2026-11-06/run-native-control.py `
  --node $node --work-dir (Join-Path $artifactRoot 'native-controls/fixed-new') --expect-recovered yes
```

Run the automatic helpers independently:

```powershell
& $node --unhandled-rejections=strict --test 'scripts/variant/file-based-apps/test-*.cjs'
& $python -B -m unittest discover -s scripts/variant -p 'test_*.py' -v
```

Prepare a normally installed publication-interruption control with the pinned inputs:

```powershell
$inputRoot = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts'
$probeWork = Join-Path $artifactRoot 'installed-publication-new'
$sharedInputs = @(
  '--base-vsix', (Join-Path $inputRoot 'fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'),
  '--base-sha256', '0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5',
  '--runtime-vsix', (Join-Path $inputRoot 'web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'),
  '--runtime-sha256', 'a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541',
  '--editor', 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe',
  '--editor-cli', 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd',
  '--dotnet', 'C:\Program Files\dotnet\dotnet.exe', '--sdk-version', '10.0.403',
  '--cycles', '2', '--work-dir', $probeWork
)
& $python -B scripts/variant/lifecycle/interrupted-publication/prepare.py @sharedInputs
& ./scripts/variant/lifecycle/interrupted-publication/run.ps1 -WorkDir $probeWork
```

The installed input is native Windows ARM64 VSCodium `1.143.17232` / API `1.143.1`, SDK `10.0.403` and observed app Core runtime `10.0.14`. The local-only extension remains version `11.7.18004`; no package is published or update completion qualified.

Regenerate the compact record from the original retained artifact layout:

```powershell
& $python -B docs/research/complete-staging-recovery-2026-11-06/summarize.py `
  --baseline (Join-Path $artifactRoot 'native-controls/baseline-01') `
  --fixed (Join-Path $artifactRoot 'native-controls/fixed-01') --tests (Join-Path $artifactRoot 'tests') `
  --checks (Join-Path $artifactRoot 'checks') `
  --installed-regression (Join-Path $artifactRoot 'installed-regression-01') `
  --installed-probe (Join-Path $artifactRoot 'installed-publication-01')
```

The collector validates executed module/driver/executable identities, actual subprocess exits, the complete pre-publication checkpoint, current guard bytes and cold-recovery results. It reparses raw focused/full Node and Python totals and verifies identical final test snapshots. Installed evidence is tied to the current modules, the executed driver/runner, native host lineage, actual exit log, intact staging receipt/payload hashes, preserved incomplete-stage guards and the real retry. Large profile/VSIX/trace data remains local; compact evidence binds its exact hashes. This change is local and unreleased; full qualification, physical F5/menu and required native macOS checks remain with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15).
