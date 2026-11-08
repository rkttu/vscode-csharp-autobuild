# PR44 review correction and trace diagnostic

This review accepts [PR #44](https://github.com/rkttu/vscode-csharp-autobuild/pull/44) as a **test/evidence-only change** after correcting its local driver and validating the correction. It preserves the original held-for-investigation disposition and failed compiler observation in [the original evidence](../host-loss-2026-11-08/README.md). The separate trace diagnostic passes but does not identify or fix the original Pause initiator. [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) remains open and blocks an all-pass qualification/release claim; [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) also remains open for its unsettled foreground/drain boundary. No product module or public package changes in this review.

## Driver correction and review findings

The original local driver could reject again while reporting an error if its root environment variable was missing or writing `driver-error.txt` failed. A discarded quit rejection was also possible. The corrected driver first verifies an absolute prepared root, normally installed Production extension mode, exact local driver identity/version/path, unpublished candidate/driver metadata and the isolated run schema. An unverified installation remains inactive and does not quit an editor. In a verified run it reports the original failure before an independently guarded artifact write, observes both synchronous and asynchronous quit failures, and completes activation promptly while the scenario continues in the background. The installed crash/restart control therefore still exercises normal reactivation.

The correction and regression cases are committed at `1b59dd3f306227940cdfc8d4cab461a4f838929c`. Fifteen isolated VM/child-process cases cover invalid preparation, successful/pending operation, synchronous/asynchronous scenario errors, artifact-write errors, and quit errors. All fifteen pass against the corrected actual driver. The same tests execute the retained original installed `n01/driver/driver.cjs` and yield **13 failures / 2 passes, exit 1**, proving the new assertions detect the old behavior. These probes perform no real editor operations or artifact writes. Their argv/environment/results/logs are separate from the unchanged five-suite Node and Python checks.

Three other automated comments were checked without changing their subjects:

| Comment | Checked disposition |
| --- | --- |
| Saving the captured session before identity assertions corrupts the replacement-host evidence | `owned-launches.json` is the failure-safety ledger and retains matching sessions for cleanup. The replacement host reads the separately published immutable `phase.json`. Observer-error and sole-session assertions reject a bad control before arming/acceptance; the full primary collector checks that checkpoint and its exact launch. |
| Ordered-map arrays do not project `.processId`, so cycle detection is ineffective | A mock-only check extracts the unchanged actual `Lineage` definition, supplies `10 → 20 → 10`, and observes `Process ancestry contains a cycle`. The projected values are `[10,20]`, and both membership checks succeed. Its source hash, helper and exact result are retained; no native process query occurs in that reproduction. |
| API version `1.143.1` can never equal editor product version `1.143.17232` | They are distinct recorded identities. Actual installed hosts report `vscode.version` / API `1.143.1`; CLI/product version is `1.143.17232`. Both remain pinned and independently checked. |

## Current native observations

| Separate control | Observed result |
| --- | --- |
| `n02`, corrected normally installed driver | PASS; editor `41008` replaces host `85652` with `74840`, exit `0` |
| Original native resources in `n02` | Exact retained host handle alone is killed; adapter `62792`, app `15232` and port `57338` release without fixture fallback |
| Ownership and retry in `n02` | Four sampled unknown DLL/PDB/sentinel/guard files remain exact; three dirty callers share one fresh build/native session, HTTP PID `99976`, then exact Stop cleans the fresh output |
| `c02`, separate trace-only compiler diagnostic | PASS in `30.554 s`, editor exit `0`; three A Stop/retry cycles, actual compiler-error handling, corrected coalesced launch, B preservation and final cleanup |

Both controls pin native Windows ARM64 VSCodium `1.143.17232` / API `1.143.1`, SDK `10.0.403`, runtime `10.0.14`, base package `11.7.18004` and exact candidate/dependency/native executable hashes. Their candidate source refs differ: `c02` uses the original PR44 ref `eed65a94f826ccb8a6178fbf6eb85e4cae82cd16`; `n02` uses the guarded-driver ref above. All five product modules retain merged PR43 content (`32eae02d4c9594be42d85f93fa1e38b079184867`) and exact current/archive/installed bytes.

`n02` follows the original primary collector's complete process/ownership/trace assertions. The new collector supplies an explicit product-identity adapter admitting only those two recorded refs and separately verifies unchanged product content from PR43. It does not edit the historical collector or remove its other checks. Native snapshots are discrete and sequential; delay labels are not calibrated cleanup-latency bounds. Unknown old output is deliberately retained and receives no fabricated terminal receipt.

## What the trace diagnostic establishes

Read-only local editor-code inspection identifies the standard Pause command's F6 binding and focused-thread/session fallback. That is a diagnostic hypothesis, not attribution of the original request. This pinned app exposes global trace through `--log trace`; no `VSCODE_LOG_LEVEL` implementation was found. The new `c02` launcher is an exact copy of shared `run.ps1` with only those two app arguments added. The original launcher/expected bytes, exact diff, new launcher hash and single expected-hash change are retained in `diagnostic-preparation.json`. Its `editorNotRun` field records preparation time, before the later one-shot launch.

The trace diagnostic retains **656 DAP rows**, zero Pause requests and zero `stopped(reason=pause)` events. Trace logging is active: renderer `CommandService#executeCommand` has **40** entries and extension-host `ExtHostCommands#executeCommand` has **88**, including **7** public file-debug command calls. There is no standard Pause-command entry or `KeybindingService#dispatch` entry. This records non-reproduction in one trace-instrumented attempt. It does not prove the original input/actor, absence of all UI input, or a fix. Trace logging changes timing. No automatic resume or test UI input masks B's state.

The unchanged historical successful compiler validator still checks passing lifecycle/build/coalescing behavior. Its optional unmodified-current-launcher equality is replaced only for this explicitly instrumented control by the stricter exact-one-delta validation above. All other shared driver/fixture hashes and executed copies remain checked. Separate offline language-service NU1100/AOT restore warnings are retained; this is not language-service readiness or an error-free-log claim.

## Original history and frozen verification

The original `n01` PASS / `c01` FAIL summary remains **397,360 bytes**, SHA-256 `febc422cdbbdf74c8a71d4bb064dffb284d5da87cc7e5798a969b20b45e313e7`. Its four documents and all original native raw-log hashes are rechecked unchanged. Full memory-only historical regeneration uses a detached original snapshot, restores only pre-run source bytes with matching recorded hashes and Git-normalized content, and maps only the source-manifest worktree identity during validation, restoring it before serialization. The raw original summary bytes match completely. An earlier Git-newline representation comparison remains separately retained; it is not another native attempt. No old editor or suite is rerun for that historical audit.

Current frozen verification archives all **53** tracked/new unignored `scripts/variant` sources with exact pre/post bytes, verification-runtime hashes, argv, environments, logs and natural results. The unchanged main suites pass **228 Node / 39 Python** cases. Separate driver verification passes **15/15**; the expected original-driver negative result remains **2 pass / 13 fail**. The original c01 failure and its sampled retained B/A-1 outputs are not converted into successful cleanup by those results.

[evidence-summary.json](evidence-summary.json) is **439,025 bytes**, SHA-256 `c5f4009f420314d8f3acf61b0c46433dbc5e0030696198d6343fe2379a2cdce1`, status `review-controls-pass-original-regression-unresolved`. It records the current evidence-only merge disposition separately from the original held disposition, with `issue45Resolved=false`, `issue18Closed=false` and `allPassQualification=false`.

Regenerate the new review summary without starting an editor or rerunning suites:

```powershell
& 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B `
  docs/research/pr44-review-2026-11-08/summarize.py `
  --artifact-root 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\pr44-review-2026-11-08' `
  --historical-root 'D:\Projects\vscode-csharp-autobuild\validation-artifacts\host-loss-2026-11-08'
```

The [original acceptance audit](../host-loss-2026-11-08/acceptance-audit.md) remains historical. The next small #18 product slice is observing known-terminal cleanup retry in the background while retaining real drain/output ownership until settlement. Current-run cleanup and user/editor-owned waits require subsequent explicit policies. Native macOS, physical F5/menu, arbitrary descendants, calibrated performance and the full repeated CI/publication matrix remain unqualified.
