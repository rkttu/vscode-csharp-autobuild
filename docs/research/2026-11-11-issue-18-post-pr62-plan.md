# Issue 18 progress review and post-62 work plan

Status: **review and proposed execution plan, November 11, 2026**. This documentation-only change is stacked on [draft PR #62](https://github.com/rkttu/vscode-csharp-autobuild/pull/62). It does not merge that PR, approve an acceptance-policy change, execute a native series, qualify a target or close [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18).

## Reviewed baseline and conclusion

- Latest merged main: [#61](https://github.com/rkttu/vscode-csharp-autobuild/pull/61), commit `025f561558214ceab691c046e439935e9b70a957`.
- Reviewed #62 head: `646855235e5330f14e509e4b4c48acff89d0e7dc`; its code checkpoint is `bffd6c48ad7d09fb276da590694fde8a6e90d2da`. Eight changed files add candidate reuse, a series controller, driver evidence, tests and guides.
- The product file-app modules are unchanged from merged #57 (`ec8bc08d38a726cd5b85a5248de03696d8af2c7b`) through this #62 head. The later work adds acceptance documentation and native-input test infrastructure, not another product lifecycle fix.
- The seven original acceptance criteria remain unchecked. The principal next step is to **use the existing controller for a prospectively frozen, actual two-profile series**, while separately resolving acceptance policy and known qualification blockers. Another speculative timer or controller layer is not the default next implementation.

These conclusions distinguish reviewed source, rerun synthetic checks and historical installed observations. They are not a claim of exhaustive bug detection or merge/release approval.

## Progress against the original criteria

The [acceptance-boundary proposal](issue-18-acceptance-proposal-2026-11-09.md) preserves the original wording and detailed evidence links. Its interpretations remain proposals, not approved replacements.

| AC | Implemented or observed progress | What still prevents completion |
| --- | --- | --- |
| 1: failure/cancellation and same-file retry | Foreground/drain separation; corrected compiler, SDK-selection and Web-profile retries; distinct-output retry for a cancelled owned handoff. | Decide the indefinitely unsettled write-capable save/provider boundary. Its source gate is intentionally retained. Complete the required installed target/scenario evidence without restarting ordinary workflows. |
| 2: cancellation around handoff | Exact late-session ownership/Stop, event-order regressions and an installed progress-Cancel control preserve unrelated sessions. | Complete required target/repetition evidence. Missing exact session events must remain uncertainty, not inferred termination or permission to delete output. |
| 3: false launch diagnostics | Declined launch, accepted-but-unconfirmed launch and cancellation have distinct outcomes; diagnostic failure does not replace the selected result. | Validate these outcomes on the required installed matrix. API acceptance and a session-start event still do not prove debugger readiness. |
| 4: actual resource cleanup and retry | Direct native SDK cancellation, session/port/output observations, terminal journals and bounded cleanup/recovery attempts. | Decide direct-owned-child versus arbitrary-descendant scope and bounded attempts versus stalled I/O. Keep separate resource observations and preserve unknown ownership. |
| 5: interrupted/reloaded host recovery | Journal-before-delete, complete staging recovery, actual Reload and guarded abrupt-host-loss controls. | Required current-candidate target coverage; preserve unmarked/ambiguous outputs and unrelated paths. Historical controls do not prove universal crash/power-loss durability. |
| 6: phase bounds and progress | Separate save, shared SDK preparation, active Web preparation and handoff guards with phase/elapsed diagnostics. | Explicit AC6 policy decision and #15 calibration. Four five-minute guards are not one total-operation deadline; editor-owned completion, event-loop/OS blocking and actual drain remain distinct limits. |
| 7: installed failures, repeated F5, concurrency and host lifecycle | Representative Windows controls; #59's separate two-input native control; #60 repeat support; #61 manual receipts; #62 frozen-series tooling. | Actual complete repetition, native macOS and remaining entry/context/Web coverage. Sequential Stop-then-F5 cycles do not test rapid duplicate F5, concurrent files or active-session Continue. |

### Native evidence must not be combined into a passing series

| Record | Actual result | Permitted conclusion |
| --- | --- | --- |
| [#59 native control](native-f5-2026-11-09/README.md) | `n01` and `n02` failed; separate `n03` passed two injected native F5 inputs in one fresh Windows ARM64 no-folder Slim HTTP profile. | Saved/dirty startup and the recorded breakpoint/HTTP/resource assertions worked for that control. Not a human hardware-key proof, ten-cycle sequence or healthy-LSP certification. |
| [#60 repeat attempts](native-f5-repeat-2026-11-09/README.md) | First series rejected the launcher parameter before GUI; successor reached its input-phase limit after observation failure. Both recorded zero native keys and zero completed cycles; neither prepared r02. | Preserve both first failures. These do not establish a product F5 failure or a passing repeated-input run. |
| [#61 manual receipts](../manual-f5-validation.md) | Unit-verified human-attestation path; no actual manual run established. | A human can declare their own observation/input. An agent cannot attest on their behalf. |
| [#62 series controller](../f5-series-validation.md) | Synthetic/tooling checks only; actual series/native/manual runs for this tooling remain **zero**. | Same-ZIP reuse and full r01 gating are implemented, not yet demonstrated by two real profiles. Even a passing series retains `qualification: false`. |

## Focused review of PR 62

The [candidate module](../../scripts/variant/lifecycle/candidate.py), [preparer](../../scripts/variant/lifecycle/prepare.py), [series controller](../../scripts/variant/lifecycle/series.py) and driver delta were inspected against the operator guides and regression tests.

- Candidate reuse checks the manifest, exact ZIP hash, current source/build identity and every payload entry before exclusively copying bytes. Validation rejection and partial I/O failure are different outcomes; partial originals are retained.
- Full r01 evidence gates **r02 preparation**, not just its launch. Verification checks ten ordered inputs per profile, exact saved/dirty revisions, raw renderer/build/DAP evidence, HTTP identity and separately timed resource observations. A zero launcher exit alone cannot pass.
- First failure is latched; retained locks/partial markers prevent success or reuse. External input closure is cooperative, not an instantaneous OS/process kill guarantee. Manual receipts remain declarations.
- #62 has six resolved review threads. The reported snapshot-key mismatch, config normalization, copy-exception fallthrough and ZIP-name mismatch do not demonstrate reachable defects in the reviewed valid-input paths. Driver snapshots use `size`, independent file proofs use `bytes`; the normalizer owns fresh JSON; an uncaught copy exception exits preparation; unsafe ZIP names are rejected before writing. An abandoned decision lock deliberately blocks reuse, while the failure path separately attempts first-failure publication and input closure. These are scoped source/test findings, not immunity to other failures.
- The queried head has one successful **Amazon Q Developer** check and no other check runs. This is an automated-review result, not a build, native-series or release qualification result.

### Validation performed for this review

| Check | Result and boundary |
| --- | --- |
| Python unittest discovery with `-s scripts/variant -p "test_lifecycle*.py" -v` | **42 passed**: candidate/preparation and series regressions, including mocked editor/native/manual execution. |
| Node `--test --test-reporter=tap scripts/variant/lifecycle/test-native-f5-input.cjs` | **48 passed**, synthetic input/receipt cases. |
| Node syntax check of `extension-test.cjs`; `series.py --help`; `prepare.py --help` | Passed. No editor or input launched. |
| Git comparison of `scripts/variant/file-based-apps` from #57 to reviewed #62 head | No changes. |
| Retained #62 `checks-final/record.json` fingerprint | 85,691 bytes; SHA-256 `6e3992cf525c99c247858cfd7852982ddb0d1eee3f366fadb86da890fe30ef4d`, matching the PR record. This checks the record file, not every archived binding. |

The focused rerun used Python 3.12.14 and the existing Node executable in an isolated checkout at the reviewed head. #62's historical **76 Python / 48 Node** report remains separately attributed; the full Python/product suites, historical evidence collectors, PowerShell parser/launcher probes and native/manual controls were **not** rerun here. VS Code did not discover tests in the isolated worktree, so the existing unittest/Node runners were used directly. No dependencies were installed and no published package or user editor profile was changed.

## Ordered follow-up work

Priorities below describe the next work, not new acceptance criteria. Dependencies are explicit; independent policy/diagnostic work need not wait for a green native series.

| Work | Priority / owner | Prerequisites | Deliverable and exit condition |
| --- | --- | --- | --- |
| W1: actual frozen Windows series | P0; #18 with [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15) | Reviewed #62 tooling, a clean exact source ref, available native target and a prepared input operator/producer | Execute the existing two-profile/ten-cycle plan. Publish either fully validated raw evidence or the first failure and investigation handoff. No new controller by default. |
| W2: AC1/4/6 disposition | P0; #18 maintainers | Existing acceptance proposal and source/ownership table; independent of W1 | Record accepted/rejected/unresolved wording and any required implementation for each boundary. This plan is not approval. Needed before AC disposition or activating qualification budgets. |
| W3: unexplained B Pause | P0; [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45), #18/#15 | Preserve original c01 and validate diagnostic capture separately; independent of W1/W2 | Identify the issuing caller or document a supported external-cause disposition. If still unknown, retain the blocker and exact missing evidence. |
| W4: entry integration and native target coverage | P1; [#16](https://github.com/rkttu/vscode-csharp-autobuild/issues/16), #15/#18 | Existing routing requirements and reviewed harness contracts; independent implementation can proceed alongside W1-W3 | Implement the existing menu/common-entry gap and native macOS runner/input support, then record separate route/target results. Do not reinterpret the Windows-only controller as portable coverage. |
| W5: fixed matrix and calibrated gates | P1; #15 with [#17](https://github.com/rkttu/vscode-csharp-autobuild/issues/17), [#20](https://github.com/rkttu/vscode-csharp-autobuild/issues/20), #18 | W2 for policy/budgets, W4 for affected routes/targets; W1/W3 outcomes inform failures and disposition | Complete the already-required scenario ledger, collect labelled phase samples/failures and review/version budgets. Unset budgets or unresolved baseline failures cannot qualify. |
| W6: acceptance and release review | Final gate; #18, [#19](https://github.com/rkttu/vscode-csharp-autobuild/issues/19), [#21](https://github.com/rkttu/vscode-csharp-autobuild/issues/21) | Evidence satisfies each original AC under explicitly approved wording; relevant W1-W5 blockers resolved | Review each AC once; keep #18 open with exact remaining requirements otherwise. Normal install/update, native/extracted-VSIX and release/public-readback gates remain separate. |

### W1: execute before expanding tooling

1. Use the existing [series workflow](../f5-series-validation.md), not a second preparer/controller. Freeze exact source/harness, executable versions/hashes, candidate inputs, application and language-server runtimes, target and separate editor/SDK/NuGet/OS-cache conditions before preparing a profile. Build the candidate ZIP once. Do not patch expected metadata or regenerate a second ZIP to make hashes agree.
2. Select one mechanism prospectively. `manual-native` requires an available human who will personally observe the intended window/editor and press each F5, then submit their own receipt. `native-injected` requires a working external producer compatible with the existing receipt protocol; `series.py` itself sends no key. Establish producer/observation readiness before the counted run, outside its artifact root. If neither is available, report W1 blocked rather than substitute a command API.
3. Keep this control to native Windows ARM64 VSCodium, a pinned stable .NET 10 SDK and the existing no-folder Slim HTTP fixture. Run r01 with saved `initial`, then nine dirty `retry-f5-N` revisions in the same window. Each input must produce one renderer route/build/owned session, source breakpoint/evaluation `marker=40`, HTTP `value=42` with matching nonce/revision/PID, and exact termination/PID-exit/port-rebind/output/queue observations.
4. Prepare r02 only after r01 passes the controller's full evidence validation. Use independent profile directories/nonces and the **same candidate ZIP bytes**, then run ten cycles and read-only `verify`. The successful aggregate must retain `completedProfiles: 2`, `completedCycles: 20` and `qualification: false`, backed by both profiles' raw results and all 31 phases per profile.
5. Stop on the first failed preparation, observation, helper, launch or assertion. Preserve attempts, raw logs, partial files and `first-failure.json`; a stale lock is not permission to delete it and resume. If r01 fails, r02 must remain unprepared. A later investigated series needs a new root and prospective plan, not a reset consecutive count.
6. Keep the 90-second driver phase and documented launcher/helper limits unchanged for this run. They are safety caps, not calibrated budgets or a total setup/installation/OS-I/O bound. Reproduce and fix a demonstrated defect separately if needed, then freeze a new source/candidate/series; never edit a live or failed series into a pass.

W1's result PR should contain the scoped report, sanitized reproducible evidence references/verifier and first-failure disposition. It should not bundle speculative product fixes, approve AC1/4/6 or close #18. If a real run fails, the first next code PR should target that reproduced cause, with a regression and a new separately identified run.

### W2: make policy decisions explicit

Use the [existing proposal](issue-18-acceptance-proposal-2026-11-09.md#criterion-decision-table), without silently weakening the [contract](../stability-contract.md).

- **AC1:** decide how retained write-capable work affects same-file retry, separately from the owned handoff/distinct-output exception.
- **AC4:** decide direct owned resources versus arbitrary descendants and bounded scan/retry counts versus wall-clock completion of stalled I/O.
- **AC6:** decide controller-owned foreground bounds versus literal finite total-operation completion; retain explicit editor/event-loop/OS and drain limits.

For each, record the decision, rationale, approved wording or outstanding implementation, evidence needed and responsible issue. If rejected or undecided, the literal unresolved requirement stays open. Do not invent an unmeasured numeric threshold or use documentation as evidence of a stronger runtime guarantee.

### W3: attribute Pause rather than hiding it

The [original failure and reviewed follow-up](pr44-review-2026-11-08/README.md) and #45 remain authoritative. The supplied local Pause-investigation note was read as additional investigation context; its collectors/probes were not rerun or promoted to public execution evidence here.

In a separate, isolated diagnostic run, verify loaded script identities and instrument the renderer's outbound `pause`, extension-host Pause command dispatch and `DebugSession.customRequest('pause', ...)`. Capture the original caller stack, arguments, session/thread, relevant extension source and UTC/monotonic correlation with edit/save/build/focus events. Validate capture with deliberate standard-command and custom-request controls first; label those as instrumentation controls, not reproductions of c01. Publish a sanitized, reproducible diagnostic record with its own pins.

If B pauses, retain session/thread/reason immediately and preserve the failed B-liveness assertion. Do not automatically Continue B, infer the caller from a tracker callback stack, blame Hot Reload/user input without evidence, or treat later non-reproduction as a fix. This work can proceed in parallel with W1, but must not change W1's frozen inputs.

### W4-W5: complete existing scope, not an unlimited new matrix

- #16 owns actual F5/menu/direct-command parity and common preparation integration. Preserve selected Project A while editing Project B, project-owned delegation, active-session Continue, user keybindings and single adapter/provider ownership. Test menu UI, native input and command API separately; do not solve menu parity by globally rebinding F5.
- #15 needs a native macOS ARM64 installed-package path with platform-appropriate identity, launch/input and resource observations. The current preparer enforces Windows ARM64 PE identity and the launcher is Windows-specific; do not bypass those guards and label the result macOS. Use a separate platform implementation and contract-compatible evidence, with an explicit manual route if needed.
- Retain rapid duplicate-F5/coalescing, independent concurrent files, cancellation, native start/process failure, disposal and crash/reload coverage. A sequential single-file series does not replace these. Use unit tests for already-covered event interleavings; add native cases for existing required scenarios or a specifically reproduced defect, not every hypothetical race.
- #17 still owns Console/Web/Console, directive/project/SDK transitions and LSP context. The passing historical native control's NU1100/project-load diagnostics are not a healthy-language-service pass.
- #20 still owns full/Slim HTTP and explicit HTTPS/certificate/browser behavior. Offline Slim HTTP evidence does not qualify network restore, full Web hosts or consent/trust flows.
- Maintain a fixed ledger of contract S01-S12 by target, route, fixture and candidate. Record current evidence, missing implementation/measurement, owner and pass/fail/not-run separately. Use two fresh profiles with ten consecutive cycles for each required scenario/target; do not pool historical candidates, routes or platforms. Different native targets require their own exact target VSIX bytes.
- Calibrate labelled cold/warm phase samples and failures before enabling reviewed, versioned qualification gates. Measurements may proceed before policy approval, but no missing budget, green automated review, unexplained rerun or unresolved #45 baseline blocker can produce qualification.

## PR and completion boundaries

This plan PR targets `stability/18-f5-series`, so its diff contains only this report and navigation links. It does not include the existing dirty main checkout. Keep #62 as the dependency; after #62 merges, retarget this PR to main and verify that only documentation remains in the diff. If #62 changes first, reconcile the pinned review and test statements rather than silently applying them to new code.

No original AC is checked by this plan. W1 can establish a useful narrow control even while policy or other targets remain open, but cannot alone close AC7 or #18. Final disposition must cite each AC's approved meaning and actual evidence, preserve unresolved failures and keep #19/#21 support/release decisions separate. Do not use an automatic issue-closing reference for this documentation or the first scoped evidence PR.
