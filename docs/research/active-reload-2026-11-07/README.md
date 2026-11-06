# Active Web session across actual editor Reload

The repaired, normally installed candidate passes actual Windows ARM64 VSCodium Reload with a live Web session: the original process, port and output are released before the replacement host starts another public command. The repair connects runtime drain to extension deactivation and accepts a narrowly scoped, explicit DAP process-exit/session-end pair when the main editor termination event does not arrive during disposal. The original and bridge-only failures remain retained for [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18).

The control invokes `workbench.action.reloadWindow` with a normally installed target candidate and a separate driver extension activated by `onStartupFinished`. The driver persists its phase in one isolated profile so a new extension host resumes the control in the same editor process.

The control is distinct from explicitly launching another app in an existing profile, intentionally crashing a host after confirmed termination, or manually disposing helper contexts while the host stays alive. It invokes the Reload command through the editor API; it does not exercise physical keyboard or menu input.

## Final repair and actual Reload result

The entry retains the runtime's activation API and returns a deactivation Promise that observes its idempotent disposal/drain. The file-runtime grace is nominally four seconds; upstream deactivation starts promptly and its result or original error is preserved. The grace clears its timer on completion and keeps late drain failures observed. It does not permit deletion of an uncertain live output or guarantee a full per-extension time budget from the editor.

The final runtime additionally permits terminal cleanup during disposal only for a cancelled, captured, exact owned launch when the same adapter tracker observes a valid `exited` event followed by a non-restarting `terminated` event. Exit codes must be signed 32-bit integers. Any restart field blocks this fallback for that tracker, and malformed/partial events, events split across trackers, cancellation without disposal and ordinary live sessions cannot use it. The existing main editor API termination path remains. Terminal marking precedes asynchronous cleanup so duplicate events and the two notification paths share ownership safely. Missing or ambiguous evidence continues to preserve output.

`installed-active-reload-02` passes on its first attempt with the final runtime. Editor **79640** remains the same app while extension host **88740** is replaced by **72456**. The old Web process is PID **19912**, port **55500**; the retry is PID **85244**, port **59750**, with a different output directory. Both hosts verify the same normally installed target payload and pinned dependency.

| Final control observation | UTC time | Outcome |
| --- | --- | --- |
| Old exact session sends DAP `exited` sequence 126, exit code 0, then `terminated` sequence 127, body `{}` | `16:22:13.811Z` | Explicit process exit plus session end |
| Replacement host's first observation | `16:22:15.905Z` | Old PID gone, port reusable, DLL/output absent, READY/STAGING empty |
| Distinct new-host initial recovery completes, before another public command | `16:22:17.748Z` | Old resources remain clear |
| New public Web retry followed by exact Stop | Subsequent recorded events | Matching termination, PID exit, reusable port, output/queues absent |

The original host records exactly one fallback confirmation for session `f397bdbb-5c22-4924-a86f-504d0ae2c30f` with exit code 0. Its recorder still sees **no main editor API termination event** for that session. The collector binds the exact fallback log line to that first host's logger and to the ordered same-session DAP events. This establishes that the fallback was exercised; an absent PID or a later command retry is not substituted for that evidence. A cancelled Stop RPC remains in the old host's diagnostics before the positive pair; the run is not an error-free-log claim.

Both actual result and runner report success, editor exit is 0, both hosts are gone, and external post-exit checks confirm both exact PIDs/ports/outputs are released. The unmarked sibling guard remains unchanged. There is no fixture HTTP shutdown or forced cleanup. The exact prepared settings file is retained and hash-checked before launch, separately from its post-editor normalization.

Final runtime SHA-256 is `198dce8e834111ac5f0e6140806ea8c0bb92ef3d1bcae9ea595fb7182b60c22f`; entry remains `8cb28056b4f634d1897302f2b97303e140e9c11c233b2f771c32f7845aab44e3`. Actual Reload candidate ZIP SHA-256 is `f4fb8afd5bd74fdce6b56832f66b5d201384f4f31bb22efc2aa1ced74b64549b`, build ID `7a867a16388bbce94c76c7c23c053d010126e2640a142322d79e7892ae197ae3`. Result SHA-256 is `b0157617633e8b25be8440fb23633dcb33465aa568bf50c4d522eba387a91360`; post-exit observation is `ac79c1491605431d2125816f26d1f2f51ec7299add088c3d3d88b20363539cb0`. Candidate `sourceCommit` identifies the base checkout at preparation; these exact module hashes identify the uncommitted repair bytes actually tested.

Final strict Node verification passes **216 tests**, with no failures, skips or cancellations, and Python helpers pass **39 tests**. Identical final test bytes against the preserved bridge-only runtime run 23 focused cases: five fail and 18 compatibility cases already pass. Tests cover API Promise compatibility, reentrant and repeated disposal, bounded drain, malformed/partial/restarting/unrelated DAP events, separate trackers, pre-disposal cancellation, unknown outcomes and API/DAP cleanup races. Final runtime-test SHA-256 is `2e8095c4838c392b1843ea3cb3a9cab78d6e8d5fc7c864f76ed24c6a5e1c3c48`.

Independent normally installed `installed-build-failure-retry-02` passes on the final product in **30.13 seconds**: actual CS0103 with no debug handoff and owned-output cleanup, dirty correction with three callers sharing one build/session, three A Stop/retry cycles, and B preservation/final cleanup. Existing Stop-time adapter diagnostics remain recorded alongside the passing behavioral assertions. Its ZIP SHA-256 is `78ee1444a74230794ca06a77ad71281d30c2a7bb1a1a671864015ce80169b544`, with the same final build ID. This separate ordinary-command regression does not claim host Reload coverage.

[evidence-summary.json](evidence-summary.json) and [summarize.py](summarize.py) bind the original failure, failed bridge-only attempt, final actual Reload, both ordinary installed regressions, both unit stages, retained source/test archives, primary local source excerpts and all selected raw file hashes. A passing final control does not erase a failed earlier stage.

## Original-baseline local shutdown audit

[audit-local-sources.py](audit-local-sources.py) binds the installed local VSCodium implementation and the **original baseline** candidate modules by whole-file SHA-256, with exact source excerpts and character offsets. The summary labels this audit's role separately from final current source. Those original bytes show:

- The extension host calls an extension's `deactivate()`, immediately disposes its subscriptions synchronously, and returns the `deactivate()` Promise. Subscription disposal is not deferred until that Promise resolves.
- Host termination races all extension `deactivate()` Promises against five seconds. That is a host-wide cap, not a guaranteed budget for any one extension.
- The pinned upstream extension's compiled CommonJS export table exposes `activate` and no `deactivate`.
- The original entry discards the file runtime activation API. Its runtime disposal starts owned cancellation/Stop work and retains observers while that work drains, but does not return a drain Promise to the extension host.

These static findings identify an integration boundary. They do not establish the actual event order or assign sole cause to a component. The active-session control below independently establishes the retained output; its first-host recording ends without confirmed session termination or a terminal receipt.

## Original active-session failure

`prototype-installed-web-01` uses editor `1.143.17232` (API `1.143.1`), native ARM64, SDK `10.0.403` and runtime dependency `3.2.0`. Native CIM lineage and nonce acknowledgements bind one editor **74508** to first host **66280** and replacement host **64692**. There is one app launch, with no `--extensionTestsPath`, injected target runtime or explicit second app launch.

The original public command starts a real Web app and verifies HTTP nonce/PID **89352** on port **62581**. A sibling unmarked sentinel is created before Reload. All timestamps below are UTC:

| Observation | Time | Original PID / port | Original output |
| --- | --- | --- | --- |
| Before actual Reload | `16:02:09.062Z` | Alive, owned HTTP response, port occupied | DLL and output exist |
| First observation in replacement host | `16:02:10.564Z` | Gone, port reusable | DLL and output remain |
| New host's initial recovery completes | `16:02:12.074Z` | Gone, port reusable | DLL and output remain; READY/STAGING empty |
| After successful public retry and exact Stop | `16:02:17.040Z` | Gone, port reusable | DLL and output remain |
| External observation after editor exit | `16:02:17.374Z` | Gone, port reusable | Output still remains |

The first host records Reload at `16:02:09.072Z` and a DAP `disconnect` at `16:02:09.081Z`. Its editor log records host exit 0 at `16:02:09.093Z`. The old-session recorder sees no later termination, exited or adapter-exit event before that host disappears. The distinct new-host output logger records initial recovery as `scanned=0, attempted=0, removed=0`; the collector verifies its path differs from the original host's logger and binds the exact log prefix. This avoids treating a late original-host log flush as new-host recovery.

A new public command in the replacement host still succeeds: PID **76820**, port **62812**, a fresh output directory, verified HTTP response, then exact Stop, matching termination, PID exit, reusable port, absent output and empty READY/STAGING. The original output remains unmarked. Recovery conservatively leaves it untouched instead of treating a dead host or process as a terminal receipt.

The result has `mechanicsCompleted=true`, `success=false` and `reloadResourcesReleasedBeforeRetry=false`. Outcome is evaluated **before** the replacement host invokes another public command, so a command-triggered retry cannot mask a Reload failure. This run needs no fixture HTTP shutdown or forced process cleanup: the original process was already gone and the retry stopped normally. The runner's `fixtureShutdown` list is empty. The unmarked sibling sentinel remains byte-identical.

Baseline source commit is `bacf917e11f9e3a929dd236de2ab25f0e16d4aab`. Runtime SHA-256 is `ac75a8bdffef7a0106e30038cf47da42de0ae63e3ee130cc3c8cdf8d2e61d952`, candidate ZIP SHA-256 is `d4d7055021fbda2913da4f6dcbb6de7bb65028b40550844818b0abb7b37edf45`, and content build ID is `6456df9f792a20f4239fa79c57eeec592246e8b5ce1faa383b89b98e3ff27043`. [summarize.py](summarize.py) validates archived/installed/current module identities, both native process lineages, pre-retry snapshots, exact post-exit resource identities, guard bytes and retained original payload hashes. Result SHA-256 is `02f9a3e90eb1d26919aca439b55893403036135428cf891a5afba3da470bb70e`; post-exit observation is `21577b9cfee8966eb00e9fd147ea402f83f74f25e3a1d83c3a1804a026691dc4`.

The prepared settings hash was checked before the app launch. After the editor run, `extensions.autoUpdate` is the string `"off"` rather than Boolean `false`; reversing only that value and serializing with the preparer's exact JSON/CRLF convention reproduces prepared SHA-256 `d21790ccb330777b67956a8618a46d5bb592bf8b6c7426f5958ef680b8747fb4`. The original prepared file was not separately retained in this baseline. The collector records the post-run file and exact reconstruction separately; `debug.confirmOnExit` remains `"never"`. No baseline artifact is rewritten to make the hashes match.

## Bridge-only intermediate remains a failure

`installed-active-reload-01` tests the first repair, which connects module `deactivate()` to idempotent runtime disposal and a nominal four-second file-runtime drain grace. It preserves activation's upstream return identity and starts upstream deactivation promptly. The file grace has a deadline and observes late failures; uncertain output is retained. The editor's separate host-wide five-second cap is an upper bound, not guaranteed time for the file runtime. This first repair passes its unit and ordinary installed-command controls, but **does not fix actual Reload output retention**.

One editor **75400** replaces host **66980** with **55924**. The original Web PID **41632** is gone and port **65522** reusable in the replacement host, but original `run-WLIUK6` and its DLL remain at the immediate observation `16:13:49.350Z`, new-host initial recovery `16:13:51.368Z`, after retry `16:13:59.790Z`, and post-exit check. READY/STAGING are empty. Retry PID **85112**, port **49256**, has normal exact Stop/PID/port/output/queue cleanup. No fixture HTTP shutdown is used.

The bridge changes what the original host can observe. The same exact session now records:

| First-host event | UTC time |
| --- | --- |
| DAP `exited`, sequence 127, exit code 0 | `16:13:45.663Z` |
| DAP `terminated`, sequence 128, body `{}` | `16:13:45.664Z` |
| DAP successful disconnect response, sequence 129, request 12 | `16:13:45.664Z` |
| Adapter exit 0 | `16:13:45.726Z` |

The editor API's matching termination event is still absent from this host's recording. Its file-debugging output records a cancelled Stop RPC. Acknowledged Stop, adapter exit, PID disappearance and a reusable port are kept separate from the product's evidence for terminal cleanup; the bridge alone does not publish a terminal receipt. These facts identify the second integration gap without assigning sole cause to one component.

The [primary DAP schema](https://raw.githubusercontent.com/microsoft/debug-adapter-protocol/main/debugAdapterProtocol.json) distinguishes debuggee process exit from the end of a debug session. `ExitedEvent` supplies a required integer exit code; `TerminatedEvent` alone does not establish process exit and can request a restart. A disposal-only fallback therefore needs the ordered pair from the same exact owned launch, with valid message shape and no restart indication. Neither event's unrelated or partial occurrence, a PID check, a disconnect acknowledgement nor adapter exit alone is sufficient.

The bridge-only source is an uncommitted candidate over the recorded base, not the Git contents at that base. Its exact modules and tests are retained under `tests/bridge-only`, validated against `archive.json`, and bound separately from the original Git baseline and final current source. Entry SHA-256 is `8cb28056b4f634d1897302f2b97303e140e9c11c233b2f771c32f7845aab44e3`; runtime is `a0527e2ed8eaa21daa6dae116ef56328f1397fdb936e63242b6f435cadf3f3aa`. Candidate ZIP SHA-256 is `0d9ad58868886017eadda2914adcd595b28b82c261fafc79bdaf93272267ec73`, build ID `a12e1a6245603fbf7a6a4d66621ed78574096db4b58099ea87bb43fcfe8aed6a`, and failed result SHA-256 `b9daa83a7e6e587956f19c0e45c203ea1182048c0dc8e63b93df2421b2c10428`. This run retains an exact prepared settings snapshot. Its driver and manifest inputs remain distinct from the earlier baseline's settings reconstruction.

Historical bridge-only verification is **193 strict Node tests passing**, with zero skips/cancellations, and **39 Python helpers passing**. Identical bridge test bytes against the original entry/runtime produce 18 failures and 78 compatibility passes in the 96-test focused run. These historical passing unit tests do not override the failed actual Reload result. Independent normally installed `installed-build-failure-retry-01` also passes on the bridge-only product in **38.40 seconds**: real CS0103, no failed-build session, dirty corrected retry with three callers sharing one build/session, three A Stop/retry cycles, and B preservation/final cleanup. Its distinct candidate ZIP is `fd8a3d2e30ca5c94ebf3e878b50e72503f5043ececbcec4ded99c8ec327adea4`, with the same bridge-only build ID. Final product verification must use separate final evidence.

## Retained harness development

The empty prototypes exercise Reload without a candidate, compiler or debuggee. Their outcomes are retained separately from the active-session control:

| Attempt | Outcome | Meaning |
| --- | --- | --- |
| `prototype-empty` | Launcher rejected its initial host identity check and closed only its exact isolated editor | Harness validation failure; no product or Reload result |
| `prototype-empty-02` | In `--extensionTestsPath` mode the first host exited with code 0 and the editor exited before a second host | Harness mode unsuitable for this Reload control; no candidate or Web session |
| `prototype-empty-03` | A normal `onStartupFinished` driver resumed after Reload: editor PID `61552`, hosts `83284` → `12512`, final exit 0 | Establishes one same-app/new-host empty Reload observation |

The local desktop workbench has an explicit test-runner-completion path that exits the native application in CLI extension-test mode. This supports using ordinary driver activation. It does not, alone, prove why the interrupted test RPC completed with code 0 in the second prototype. No passing later attempt erases either earlier failure.

## Scope

Native macOS, physical F5/menu input, arbitrary active-host crashes, descendants, interrupted/incomplete ownership publication, full queue fairness and filesystem deadlines remain outside this slice. Unknown or unmarked output remains preserved rather than being reclassified as terminal from a dead host PID. Single observations and the runner's safety deadline do not establish latency budgets or release qualification.

## Revalidation without another editor launch

The original failure can be validated against its pinned Git product and retained, hash-verified `executed-harness` snapshot while the repair source changes independently:

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$artifactRoot = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\actual-reload-2026-11-07'
& $python -B docs/research/active-reload-2026-11-07/summarize.py `
  --artifact-root $artifactRoot `
  --run-dir (Join-Path $artifactRoot 'prototype-installed-web-01') `
  --expected-product-outcome retained --historical-product `
  --output (Join-Path $artifactRoot 'baseline-revalidated.json')
```

Regenerate the complete committed summary from all retained runs, without rerunning tests or launching an editor:

```powershell
& $python -B docs/research/active-reload-2026-11-07/summarize.py `
  --artifact-root $artifactRoot `
  --baseline-dir (Join-Path $artifactRoot 'prototype-installed-web-01') `
  --intermediate-dir (Join-Path $artifactRoot 'installed-active-reload-01') `
  --intermediate-product-archive (Join-Path $artifactRoot 'tests/bridge-only') `
  --bridge-regression (Join-Path $artifactRoot 'installed-build-failure-retry-01') `
  --run-dir (Join-Path $artifactRoot 'installed-active-reload-02') `
  --expected-product-outcome clean `
  --installed-regression (Join-Path $artifactRoot 'installed-build-failure-retry-02') `
  --tests (Join-Path $artifactRoot 'tests/final')
```

The final candidate and harness must match current source bytes. The original Git baseline, dirty bridge-only archive and final current product are separate identities; the source audit describes the original installed entry/runtime. Final prepared settings must exist as an exact input snapshot. Unit and ordinary build-failure/retry evidence remain separate from actual Reload evidence.

## Fresh actual Reload control

Run from the repository root on the native Windows ARM64 toolchain. This example uses the retained original-control VSIX as a concrete pinned packaging base, replacing its owned modules with current source. A fresh preparation receives its own candidate/build identity; it is not expected to reproduce a prior ZIP digest. The pinned dependency is the same runtime VSIX used above.

```powershell
$fresh = Join-Path $artifactRoot 'installed-active-reload-new'
$resources = 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\web-lifecycle-2026-11-05\resources'
$editorRoot = 'C:\Users\rkttu\AppData\Local\Programs\VSCodium'
& $python -B scripts/variant/lifecycle/active-reload/prepare.py `
  --base-vsix (Join-Path $artifactRoot 'prototype-installed-web-01/local-lifecycle.vsix') `
  --base-sha256 d4d7055021fbda2913da4f6dcbb6de7bb65028b40550844818b0abb7b37edf45 `
  --runtime-vsix (Join-Path $resources 'ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix') `
  --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor (Join-Path $editorRoot 'VSCodium.exe') `
  --editor-cli (Join-Path $editorRoot 'bin/codium.cmd') `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --work-dir $fresh --cycles 2 --scenario web-lifecycle
& scripts/variant/lifecycle/active-reload/run.ps1 -WorkDir $fresh -DeadlineSeconds 240
```

The active-reload preparer installs the default Web fixture and selects a random loopback **HTTP** endpoint through its run settings. It replaces the test-runner entry point with ordinary `onStartupFinished` driver activation and records `debug.confirmOnExit="never"`. The launcher uses no `--extensionTestsPath`, launches one isolated app, verifies both host lineages through nonce acknowledgements, and restores its process environment. It refuses a repeated attempted directory. All control deadlines are harness safety limits; original failed results remain in their own directories. Cleanup targets only captured exact sessions or nonce/PID-verified fixture endpoints, with an exact isolated app ownership check on failure.
