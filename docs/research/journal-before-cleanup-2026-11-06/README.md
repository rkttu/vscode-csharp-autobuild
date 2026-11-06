# Publish terminal cleanup receipts before recursive deletion

This follow-up to [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) closes a gap at the **first terminal cleanup attempt**. Previously, the runtime tried recursive deletion directly and published a recovery receipt only after deletion rejected. If the host exited during that first deletion, a partly deleted output could remain without a published receipt. A fresh activation correctly refused to infer deletion permission from its pathname, age or the previous host's exit.

The runtime now publishes terminal ownership before calling recursive deletion, then delegates deletion to the existing recovery module. The version-1 receipt stays beside the fixed `output` child throughout deletion. Publication or identity failures retain owned output for a bounded later retry. Confirmed `ENOENT` can complete without a receipt only if no incomplete publication is tracked. The recovery format, scan bounds and validation guards are unchanged.

The [evidence summary](evidence-summary.json) binds source, raw tests, normally installed VSCodium regression and the following real process-boundary control. This remains partial lifecycle evidence rather than complete host-crash qualification.

## Actual native Node process boundary

The same [driver](native-control.cjs) uses the actual product runtime and recovery implementation with a real filesystem. SDK results and VS Code API events are controlled. It first starts an independent **stub debug session** through the runtime, then makes a second source's controlled build fail. At the first recursive removal callback, it inspects the journal, deletes one actual leaf, records the remaining payload and exits with code `73` before that removal promise settles. A second native Node process activates a fresh runtime and awaits its normal `recoveryReady` operation.

| Control | Interrupted / cold PID | First deletion | Cold recovery | Residual |
| --- | --- | --- | --- | --- |
| Baseline `5e98bf8…` | `86092` / `86640` | No published receipt | scanned 0, attempted 0, removed 0 | Preserved without a receipt; gap reproduced |
| Final runtime | `64920` / `72804` | Complete v1 receipt already published | scanned 1, attempted 1, removed 1 | Exact queued output removed |

Both interrupted processes exit `73`; both cold processes exit `0`. Baseline control success means the old gap was reproduced, **not that its desired behavior passed**. Its `desiredBehaviorObserved` value is false. The fixed control's value is true. The two cases use identical driver and recovery bytes; only the runtime changes. The driver snapshots, exact native executable/hash, subprocess commands, PIDs, exit codes, synced boundary traces and filesystem proofs remain under `native-controls/`.

After the fixed runtime moves the terminal output into its published journal, the driver recreates the original `run-*` path with a replacement sentinel. Cold activation removes only the queued terminal child and preserves that replacement. Both cases also preserve byte-identical unmarked output, the independent active stub-session's output, unpublished staging and a sentinel outside extension storage. The cold activation performs no SDK selection, debug launch or Stop. The replacement control covers recreation **after publication**.

This is a real abrupt native Node exit and a new native process, with controlled SDK and editor APIs. It does not establish actual debugger child exit, an extension-host crash, editor reload, macOS behavior or arbitrary interruption before a complete receipt is published. Unpublished staging and uncertain/live output intentionally remain untouched.

## Normally installed extension-host interruption

A separate control, `installed-interruption-04`, uses the normally installed local candidate and runtime dependency in isolated native Windows ARM64 VSCodium. A separate development test driver invokes the public file-debug command and uses the actual SDK/native debugger. At the exact first terminal deletion, a scoped filesystem hook confirms matching session termination, debuggee PID exit and port reuse, confirms the published v1 receipt, unlinks the PDB and waits for an external acknowledgement of its exact extension-host process. It then calls `process.exit(73)` inside that actual host.

Native process inspection links extension host **55180** directly to editor process **88776**, with the exact executable, isolated profile command line and creation times retained. VSCodium's own `main.log` records host PID 55180 exiting with code **73**. The first editor also exits naturally with code 73; the launcher does not need to kill it. An **explicit second app launch** reuses that isolated profile. Its new extension host **89120** recovers the published terminal entry, preserves the unmarked/external sentinels and the replacement recreated at the original path, then starts and cleans a real public-command retry.

| Observation | Recorded value |
| --- | --- |
| Original real debuggee, before controlled host interruption | PID `5316` gone; port `62798` reusable |
| Published interrupted entry | `4541c86e-47c2-4a19-980a-c311af8a9181`, receipt version 1 |
| First editor / extension host | `88776` / `55180`, observed natural editor exit 73 |
| Explicit second editor / new extension host | `40600` / `89120`, final editor exit 0 |
| Same-profile real retry | PID `52448`, port `63774`, HTTP value 42, matching termination and owned output/queue cleanup |
| Actual run interval | November 6, 2026, `21:15:57.464` to `21:16:15.510` KST; raw records retain UTC |

Final post-exit observation confirms the terminal entry and retry output are absent and all three sentinel hashes remain unchanged. Its process query checks command lines containing this isolated work path and excludes the observer; it is not a complete descendant-process assertion.

This verifies one **published terminal-cleanup interruption followed by explicit app relaunch**. The debuggee had already terminated before host exit. It does not qualify active-debug-session crashes, automatic editor reload, interruption of incomplete staging, physical F5 or macOS. The injected hook and intentional exit are recorded separately from the product runtime. Preparations 01, 02 and 03 were never launched: pre-launch review added hook-failure/hash evidence, reliable environment restoration and loaded dependency/version assertions. Each superseded preparation remains retained; 04 is the first executed installed interruption attempt.

## Automated and installed regressions

Five focused regressions execute with identical final test bytes before and after the change: all five fail the old runtime and pass the final runtime. They cover a published receipt before the first deletion, partial deletion and fresh activation, unavailable directory identity, incomplete tracked publication when the original disappears, and already-absent terminal output. The final strict suite passes **156 tests with zero skips**; Python helpers pass **39 tests**.

The initial four-case/full-suite checks are retained separately. Four assertions in the first full run assumed deletion of the original `run-*` path; they were updated to follow its published journal output. A subsequent review found the incomplete tracked-publication edge, added the fifth regression and produced the final `8b6c702…` runtime. The earlier 155-test result and the preparation made before that guard are historical, not the final candidate's qualification. Raw commands, source/test hashes and each first failure remain retained in `tests/`.

Normally installed native Windows ARM64 VSCodium `installed-regression-02` also passes on the final source in **23.86 seconds**. It exercises real SDK/native debugging, breakpoint evaluation, actual CS0103 failure, three concurrent corrected callers sharing one fresh build/session, three A Stop/retry cycles, exact PID/port/output/queue checks and preservation/final cleanup of independent real Web session B. This is separate from the stubbed Node interruption control. Preparation `installed-regression-01` was superseded before launch and is retained with an explicit unattempted record.

| Input | Value |
| --- | --- |
| Baseline commit | `5e98bf8fa6f78264f28220a8e2be13af84197818` |
| Final runtime SHA-256 | `8b6c70233942e2ee72d817b00fdbca7920b5ec4d6955ed6581dabf2cac68ffa2` |
| Final runtime-test SHA-256 | `e3648e72284a4513f119416da05474c9dc9e2b82466a6ee5208a09ea6c1aad9e` |
| Installed regression candidate SHA-256 | `19d5e93f37f0ae5a6693d9b4dc068af9b210457361c8e1604ff03450020dda29` |
| Installed regression build ID | `e976a738c49cd79c061bf8e2bd6659a7176ddc69682ab0336fe7f914935f6a8b` |
| Installed interruption candidate SHA-256 | `6af1b94e4bd3ce696a96f09abbb1cc9437bffee17975dbaae59f64238b52af09` |

The two candidate archive hashes differ while their product build ID and owned module hashes match. They were prepared separately from the same final runtime. The dedicated installed-control source hashes and exact loaded module/dependency identity are retained in the summary.

The local candidate is not published. Physical F5/menu, required native macOS checks, the full repeated scenario matrix and calibrated qualification gates remain in [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15). #18 retains the other interruption boundaries and lifecycle work. Existing offline language-service restore warnings are outside these runtime cleanup controls.

## Reproduction

Use a fresh directory for every attempt. The runner refuses nonempty work directories and preserves unexpected exits in `first-failure.json`; it never sweeps previous outputs. The interrupted process intentionally leaves its fixture artifacts for inspection.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/journal-before-cleanup-2026-11-06'
$driver = 'docs/research/journal-before-cleanup-2026-11-06/run-native-control.py'
& $python -B $driver --node $node `
  --work-dir (Join-Path $artifactRoot 'native-controls/baseline-new') `
  --runtime-ref 5e98bf8fa6f78264f28220a8e2be13af84197818 --expect-published no
& $python -B $driver --node $node `
  --work-dir (Join-Path $artifactRoot 'native-controls/fixed-new') --expect-published yes
```

The runner snapshots the selected runtime and baseline recovery module into each case. It checks that the recovery module remains equivalent to the current product source, then uses the exact same recovery snapshot bytes for both cases. It records the current runtime-test file for provenance without executing those tests inside the native control.

The full automated checks can be run independently:

```powershell
& $node --unhandled-rejections=strict --test 'scripts/variant/file-based-apps/test-*.cjs'
& $python -B -m unittest discover -s scripts/variant -p 'test_*.py' -v
```

For the installed interruption control, use the pinned base/dependency/editor/SDK inputs retained on this machine and another fresh work directory:

```powershell
$inputRoot = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts'
$probeWork = Join-Path $artifactRoot 'installed-interruption-new'
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
& $python -B scripts/variant/lifecycle/interrupted-cleanup/prepare.py @sharedInputs
& ./scripts/variant/lifecycle/interrupted-cleanup/run.ps1 -WorkDir $probeWork
```

Regenerate the compact record from the retained original artifact layout:

```powershell
& $python -B docs/research/journal-before-cleanup-2026-11-06/summarize.py `
  --baseline (Join-Path $artifactRoot 'native-controls/baseline-01') `
  --fixed (Join-Path $artifactRoot 'native-controls/fixed-01') `
  --tests (Join-Path $artifactRoot 'tests') --checks (Join-Path $artifactRoot 'checks') `
  --installed-regression (Join-Path $artifactRoot 'installed-regression-02') `
  --installed-probe (Join-Path $artifactRoot 'installed-interruption-04') `
  --prepared-only (Join-Path $artifactRoot 'installed-regression-01') `
    (Join-Path $artifactRoot 'installed-interruption-01') `
    (Join-Path $artifactRoot 'installed-interruption-02') `
    (Join-Path $artifactRoot 'installed-interruption-03')
```

The summarizer verifies exact before/after module and driver identity, real subprocess boundaries, current sentinel bytes, the published first-delete target and cold recovery result. It reparses raw Node/Python counts, validates test-command/output bindings, and reuses the existing installed-editor validator for exact loaded candidate identity, sessions/resources and log slices. The dedicated installed probe additionally validates module/driver pins, host/editor native lineage, host exit log, both launch outcomes, first-delete receipt and resource observations, preserved sentinel contents and the real retry. Large profiles, VSIX packages and full traces remain local; their exact identities and first evidence are retained by the compact record.
