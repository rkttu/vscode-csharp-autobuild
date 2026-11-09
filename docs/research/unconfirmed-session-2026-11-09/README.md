This change explains an owned file launch whose editor API accepted `true` before an exact start event was observed. It adds one best-effort output entry with the program and retained output, one confirmation after a matching late event, and a disposal entry identifying the retained launch's request/session state. Boolean results, deadlines, exact-session Stop, terminal cleanup and drain policy remain unchanged. Late acceptance after cancellation remains a false, quiet command result; its entry includes `cancelled=true`.

Source commit `97ed767b789fe9bcd1e88889fa4ec18cd0cfe496` changes only runtime.cjs, test-runtime.cjs and [the user documentation](../../file-based-apps.md), relative to merged base `b2549b9c4eb7f12b1272468021d2de9ab761ae09`. The runtime diff adds ownership-state and diagnostic bookkeeping. It adds no timer, notification, speculative Stop or cleanup authority.

The retained checks below used strict unhandled-rejection handling and TAP. The full strict Node file-app suite covers the five classify, entry, recovery, runtime and Web test files. Every run has zero cancelled, skipped or TODO cases.

| Recorded check | Base runtime | Changed runtime |
| --- | --- | --- |
| Selected `^unconfirmed launch diagnostics` | 5 intended assertion failures, 1 safe PASS | 6 PASS |
| Full Node | — | 321 PASS |

The selected cases cover accepted-but-unconfirmed output retention and a coalesced fresh-output retry; exact late confirmation with unrelated/duplicate events ignored; quiet cancellation followed by late acceptance and exact-session Stop; disposal with pending, accepted or captured ownership; already-observed/terminated/declined/rejected safe controls; and throwing diagnostic sinks with reentrant disposal or termination. The last changed-code case executes seven modes. Its baseline run stops in the first `accepted-throw` mode at a missing-confirmation assertion. The five baseline failures all assert absent diagnostics; they do not reproduce an earlier unsafe Stop or cleanup. Current-source assertions supply the resource-preservation and reentrancy witnesses.

The root recorded one contrast attempt and one full attempt under `validation-artifacts/unconfirmed-session-2026-11-09/checks/initial-{contrast,full}`. Each preserves its exact runner, before/result/final records, UTC times, original argv and executable identities, raw logs, and 54 source files: all 53 variant files plus the separate user document. Both archives and final source hashes agree; current bytes match them, and Git comparisons bind every source to the source commit modulo CRLF/LF. All other variant files equal the merged base. Contrast preserves six module copies per side; only baseline runtime.cjs is replaced by the exact raw base Git blob. The same current tests run on both sides.

| Raw log | Bytes | SHA-256 |
| --- | ---: | --- |
| `checks/initial-contrast/baseline.log` | 5,606 | `b3ad48f47821fb7a3defba812800780018da7b1490ad575e047fffd6a3053077` |
| `checks/initial-contrast/changed.log` | 1,886 | `f6c778d35c6b97ac72bc032adda444b66b2da69fd0c9c9e5ac1ce7dc3d1f402a` |
| `checks/initial-full/full.log` | 77,929 | `9cea8be67579197d7b85f8e24b31a8d0fba1dbfd27678577abd67d8b8e076795` |

[verify.py](verify.py) is a standalone read-only verifier. It checks the two pinned final records, their before/result records, three raw logs and rendered TAP outcomes, all source archives/current/Git bindings, contrast copies, archived runner and capture helper, and every executable pre/post snapshot. Its JSON retains the five LF-normalized failure diagnostics, including source positions, and hashes their exact untrimmed bodies. It imports no earlier research collector and launches only read-only Git commands. It reads content-addressed retained Node/Python EXE bytes, while validating the original execution-path/argv identities recorded by the checks. It does not read the original cache EXEs or execute the retained copies. EXE retention is not a complete Python environment, standard-library or operating-system archive. This record makes no exhaustive execution-history claim.

The selected cases use controlled editor/session and process-provider fixtures, with temporary filesystem output. They do not establish that a real VSCodium launch loses an event, that the debuggee is ready, or that diagnostics are delivered in order. No native editor, unchanged Python suite or separate driver suite was rerun for this diagnostic-only slice. The full Node suite includes its existing real child-process tests. The [public API](https://code.visualstudio.com/api/references/vscode-api#debug.startDebugging) exposes the Boolean start result and session events separately; the [extension-host implementation](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/api/common/extHostDebugService.ts) also separates the start RPC from event acceptance. Those interfaces do not justify an event-delivery guarantee or a speculative Stop without an owned session. Logging can fail without replacing the launch result, and missing reliable terminal evidence can still retain output and disposal indefinitely.

Existing foreground budgets cover dirty Save, SDK/build work, noninteractive Web preparation and the owned file-start API wait. Actual OS completion, drain and missing session events have no safe finite guarantee. Certificate interaction and editor-owned project delegation remain intentional exclusions. Full #18 acceptance still requires safe-policy acceptance and the specific native fault matrix, macOS and F5 qualifications; #45's unknown Pause is separate. This slice supplies diagnostic evidence, not full AC6 or release qualification.

To verify retained evidence without rerunning checks, from the project root in PowerShell:

```powershell
$artifact = 'D:/Projects/vscode-csharp-autobuild/validation-artifacts/unconfirmed-session-2026-11-09'
& 'C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B "$artifact/worktree/docs/research/unconfirmed-session-2026-11-09/verify.py" $artifact
```

The CLI calls `build_summary(Path)` and emits `(json.dumps(value, indent=2) + '\n').encode('utf-8')` as canonical LF bytes. Its memory result and CLI output matched [evidence-summary.json](evidence-summary.json): **14,126 bytes**, SHA-256 `70a57964fcf25391906724e226178406df56c1e512b51715a372d5103ef44f66`.
