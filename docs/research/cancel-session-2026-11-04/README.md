# Cancellation during debugger handoff: local API control

On November 4, 2026, the cancellation change passed a Windows ARM64 control using VS Code 1.144.1, .NET SDK 10.0.403/runtime 10.0.14, and the native adapter from the normally installed public 11.7.18004 VSIX. The [summary](evidence-summary.json) retains versions, exact local file hashes, scope flags, assertions and observed event timings.

The editor driver loads the current repository-owned runtime directly. It delegates session events, start/stop requests, compilation and debugging to real APIs, while injecting progress cancellation and holding the first configuration-provider request. It does **not** exercise the installed active-file command, physical F5, VSCodium or macOS. This is a local control, not release qualification under the [stability contract](../../stability-contract.md).

## Observations

- Seven of eight initial handoff tests failed against the previous runtime; the uncancelled-rejection control passed. The final logic suite passes 71 Node tests and 34 Python tests, including nine added handoff cases.
- The first implementation cleaned output when the stop Promise resolved. A strengthened real-editor check failed: 59 ms after that resolution, the DLL was gone while the termination event was still pending. This records event ordering, without claiming the debuggee remained alive during that interval.
- The final runtime waits for the matching termination event. In the successful control, the DLL existed at stop completion, 60 ms later, and in the termination observer; cleanup then completed.
- The cancelled foreground command returned before the held start request completed. The later session retained its output/program fields, and only that exact session was stopped.
- Same-file retry used fresh output, stopped at the real source breakpoint on line 3, and evaluated `answer` as `40`. Normal termination cleaned the retry output. All five editor checks passed, with no error notification.

These timings are observations from individual local runs, not latency budgets or repeated-workflow qualification. The implementation preserves output if termination is never confirmed. Whole-operation deadlines and recovery after host shutdown, reload or crash remain in issue #18.

## Retained driver and local reproduction layout

The driver, preparation and launcher scripts are exact copies of the local control, with their hashes recorded in the summary. They expect the following layout beneath a repository checkout:

```text
validation-artifacts/cancel-session-2026-11-04/probe/       # copy these scripts here
validation-artifacts/cancel-session-2026-11-04/worktree/    # checkout of this change
validation-artifacts/fba-f5/editor-smoke/portable-code/     # Windows ARM64 VS Code 1.144.1
validation-artifacts/fba-web-snippets-release-2026-11-03/
  readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix
  editor-web/extensions/ms-dotnettools.vscode-dotnet-runtime-3.2.0/
```

With those local prerequisites and the matching SDK installed at `C:\Program Files\dotnet`, run `prepare.py`, then `run-editor.ps1` from the copied probe directory. The script uses a dedicated profile, extension directory, APPDATA and .NET CLI home; it disables extension updates. The test runs in a separate extension host and writes `editor-result.json`. The final editor process exited with code 0.

`summarize.py` additionally expects the earlier `before-terminal-guard.json`; that raw red result and the final raw log remain local artifacts, whose hashes are in the summary. They are not required to rerun the successful control. The summary's runtime hashes refer to exact local bytes, including their line endings; they are not package integrity identities or a published version.
