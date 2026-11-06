# Retry terminal output recovery on a later valid command

This follow-up to [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) addresses a bounded startup recovery pass that encounters a temporary filesystem failure. Previously that activation did not scan the previous owner's receipt again: only a later app activation could retry it. A receipt published after the startup scan had the same gap.

A valid saved-file command can now start another bounded recovery pass in the background. Commands share a pass already in progress and do not queue a second pass behind it. One local failed cleanup takes precedence over starting a global scan, and an existing local cleanup suppresses a competing scan. The existing recovery module retains its combined limit of 32 inspected entries and one eligible attempt, fixed-child deletion, schema and physical-path guards.

The background promise also retains disposal ownership. A graceful activation disposal stops new passes while diagnostics and session observers remain available until the existing pass and other owned work drain. `recoveryReady` continues to describe the initial pass. Pass counts are written to the existing C# File Debugging output channel; failures do not add launch-error notifications.

## Native process control

The [driver](native-control.cjs) uses the actual product runtime/recovery and native filesystem with controlled SDK results and VS Code APIs. A writer process builds a controlled failing source, creates a real terminal receipt, moves the complete output through the normal publication path, and exits with code 73 at the first deletion callback before executing recursive deletion. A distinct reader process activates against the same storage. Its first exact old-output deletion throws an injected `EBUSY`, and the initial `recoveryReady` settles with scanned 1, attempted 1, removed 0.

After unlocking that exact output, the same reader PID invokes its registered public command. The baseline retains the old receipt. The fixed reader starts another bounded pass and removes it without restarting the reader. In the fixed control, the new deletion deliberately waits for a gate released only by the new stub session's `startDebugging`; its controlled build waits until that deletion has entered. The baseline bypasses that SDK gate because it never starts the retry, then observes the intact old receipt for 100 ms after its command resolves. These controlled timing differences are recorded in each input; the runs do not claim identical injected timing. This establishes that the foreground command progresses while recovery is still pending. It is an ordering proof, not a wall-clock performance benchmark.

Both cases use the exact writer runtime and recovery from merged [#33](https://github.com/rkttu/vscode-csharp-autobuild/pull/33), commit `bc94c900acadd09fd29a949497818b4c36b43edb`. Both reader recoveries use that same Git snapshot, and both execute identical driver bytes. Only the reader product runtime changes from the Git snapshot to the final current source; expected-outcome and controlled-timing inputs also distinguish the cases as described above. The retained final test-runtime snapshot is provenance, not executed native-control code. Raw LF Git bytes and working-tree line endings keep their separate hash identities.

Both first executed controls pass their expected conditions:

| Control | Writer / same reader PID | Observed exits | Startup recovery | After valid command |
| --- | --- | --- | --- | --- |
| Baseline `bc94c900` | `86540` / `91612` | `73` / `0` | scanned 1, attempted 1, removed 0 | Old READY receipt and intact payload remain |
| Final runtime | `68596` / `77100` | `73` / `0` | scanned 1, attempted 1, removed 0 | One further pass: scanned 1, attempted 1, removed 1 |

The result SHA-256 values are `d97fd6acb069398786af1ab3fd6ebbdb6340bb93c1c0727d581ea9f0aa4e3f8e` and `d970a099d0ae370707044221bfdd11ea42369257789811dd173d06760d4ab59d`. The writer and both reader recoveries execute Git LF recovery bytes `14630c1b…c05ae`; the unchanged working-tree/installed recovery is `099f74d6…99d4` with CRLF. Their normalized source is identical.

Four unrelated guard files remain byte-identical: an unmarked output, an external sentinel, a replacement recreated at the original source-output pathname after publication, and a valid record-only STAGING receipt. The fresh reader output must exist during its stub session and clear after an exact Stop; disposal must then drain. These controls do not claim actual SDK, editor, debugger, Web server or debuggee behavior.

## Normally installed same-host control

`installed-command-recovery-01` passes on its first actual attempt in native Windows ARM64 VSCodium. The target candidate and pinned runtime dependency are normally installed in an isolated profile; only an empty separate test driver uses a development path. Native process inspection and a nonce handshake bind editor **86296** to extension host **84896**. The same app and host remain throughout, and the editor exits successfully with code 0.

After a real Web B session reaches HTTP readiness, a separate installed recovery-controller instance publishes a synthetic known-terminal receipt after the target activation's initial scan. The target runtime has never owned that fixture's original run path. This is a synthetic terminal payload, not an actual previous host or debuggee. A hook affects only `fs.promises.rm` for that exact queued output.

Three concurrent public A commands start one actual SDK/debugger/Web session while that deletion is deliberately blocked. The actual observations are:

| Observation | Recorded value |
| --- | --- |
| Exact fixture deletion enters | `13:20:50.632Z` |
| A reaches real HTTP readiness while deletion is pending | `13:20:54.492Z` |
| Gate opens and the first pass rejects with `EBUSY` | `13:20:54.501Z` |
| A initial / corrected retry PID | `45648` / `55140` |
| Independent B PID | `6500`, same token/PID/HTTP response until final Stop |
| Editor / extension host PID | `86296` / `84896`, unchanged |
| Fixture removal calls | Exactly two: one busy failure, one later success |

The failed pass retains the receipt and intact synthetic payload. Stop clears A's own output without queuing another pass. A later dirty correction and three concurrent public commands start one fresh real Web A and remove the old fixture in one additional pass. The output log contains exactly four pass completions: two initial `0/0/0`, then `1/1/0` and `1/1/1` for scanned/attempted/removed. It also contains exactly three SDK builds and handoffs, one per real B/A/A session.

External post-exit checks confirm all three exact debuggee PIDs are gone, all three ports can bind and all captured outputs are absent. READY is empty; only the deliberately valid record-only STAGING receipt remains. Unmarked, external, original-path replacement and incomplete-receipt sentinels remain byte-identical. The actual installed result, first gate ordering, complete output log, current/archived/loaded module hashes, harness snapshots, candidate and native lineage are all validated by [summarize.py](summarize.py).

The candidate SHA-256 is `a6ec6843ba9e0e9d6595605cec50ad0d4a501b85b93121a442a6c572b6eb0af3`, with local build ID `54f1bffca8aa19e152eed65201a485e6db1b027a091814a306fe6214480c1ab5`. Result SHA-256 is `f9b87a2fe608caf8efbbcfa9a9e317b107f5a5b16ea16a7c3112537245091247`; post-exit observation is `dd14722da38e90aab8a5febc702ae0aaedf88ef317a8ed8e0dccd6d4e591c4a1`. There are no failed native or installed-editor attempts in this slice.

Normally installed `installed-regression-01` separately passes in **23.05 seconds** on the same final product build. It retains the actual breakpoint/marker evaluation, CS0103 build failure with no session, dirty correction with three callers sharing one build/session, three A Stop/retry cycles while B remains live, and exact final B cleanup. Its candidate ZIP has a separate SHA-256 `430f22e1809eb759488544a95fac8c3946a37982a01b20be503ddc0d5a338fb4` and the same build ID. The compact summary retains the separate ZIP identities.

## Automated regressions

Identical final test bytes run 11 focused cases against the old and final runtimes: the baseline has nine failures and two compatibility passes; the final runtime passes all 11. The full strict Node suite passes **182 tests with zero skips, cancellations or failures**, and the Python helpers pass **39 tests**. Focused cases cover previous-owner startup failure, later READY and complete STAGING publication, nonblocking/coalesced commands, disposal before scheduled I/O, reentrant disposal, local retry priority, an existing terminal cleanup and unexpected later rejection/throwing diagnostics.

Raw historical attempts remain retained. An early baseline fixture left an SDK gate pending when the old runtime failed as expected; its exact owned test child was verified and terminated, and teardown was added. An initial after run exposed an observation race: the filesystem entry was absent before the owning cleanup Promise had drained. The test now lets that I/O completion settle before issuing the next command. These preparatory failures and source hashes remain in `tests/implementation-summary.json`; final outputs are `focused-before-final.txt`, `focused-after-final.txt` and `full-after.txt`.

Final runtime SHA-256 is `ac75a8bdffef7a0106e30038cf47da42de0ae63e3ee130cc3c8cdf8d2e61d952`; final runtime-test SHA-256 is `d31cfa4c3e515c43972bc2d166ef566327cf0ee39a34e373f71fcca9cd84ba14`.

## Scope

This change retries eligible terminal receipts after a transient failure or later publication without requiring another activation. It does not establish that a dead host or PID makes an unmarked active-session output terminal. Active-session host loss, automatic editor Reload, native macOS behavior, descendant processes, full queue fairness, I/O deadlines and power-loss durability remain outside this slice. Unknown, incomplete or malformed entries remain preserved under the existing recovery protocol.

The raw native outputs, source snapshots, trace order, subprocess arguments and observed exit codes are retained outside Git. The committed compact summary binds those files by SHA-256 and validates the actual current product, test and research-script bytes. Baseline control success means the previous no-retry gap was reproduced; its `desiredBehaviorObserved` is false.

## Reproduction

Use a fresh work directory for every executed control and retain the first result:

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$artifactRoot = Join-Path (Get-Location) 'validation-artifacts/command-recovery-retry-2026-11-06'
& $python -B docs/research/command-recovery-retry-2026-11-06/run-native-control.py `
  --node $node --work-dir (Join-Path $artifactRoot 'native-controls/baseline-new') --reader-runtime baseline
& $python -B docs/research/command-recovery-retry-2026-11-06/run-native-control.py `
  --node $node --work-dir (Join-Path $artifactRoot 'native-controls/fixed-new') --reader-runtime current
& $python -B docs/research/command-recovery-retry-2026-11-06/summarize.py `
  --baseline (Join-Path $artifactRoot 'native-controls/baseline-new') `
  --fixed (Join-Path $artifactRoot 'native-controls/fixed-new')
```

The runner refuses a nonempty work directory. Only its own exact subprocess is terminated if the safety deadline expires. No process-name or tree sweep is used. The evidence collector can additionally bind final strict Node results, Python helper results and both normally installed-editor controls using `--tests`, `--checks`, `--installed-regression` and `--installed-probe`. The installed same-host harness is under [scripts/variant/lifecycle/command-recovery](../../../scripts/variant/lifecycle/command-recovery). Its source comments and result scope keep the synthetic terminal fixture separate from the actual A/B SDK/debugger/Web sessions.

To revalidate all retained first-attempt evidence without relaunching any editor:

```powershell
& $python -B docs/research/command-recovery-retry-2026-11-06/summarize.py `
  --baseline (Join-Path $artifactRoot 'native-controls/baseline-01') `
  --fixed (Join-Path $artifactRoot 'native-controls/fixed-01') `
  --tests (Join-Path $artifactRoot 'tests') --checks (Join-Path $artifactRoot 'checks') `
  --installed-regression (Join-Path $artifactRoot 'installed-regression-01') `
  --installed-probe (Join-Path $artifactRoot 'installed-command-recovery-01')
```
