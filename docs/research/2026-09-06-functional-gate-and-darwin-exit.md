# Upstream functional gate and Darwin exit-code compatibility

On September 6, 2026, release preparation expanded the netcoredbg gate from the
repository's eight-check fixture to Samsung's 30 automated DAP scenarios on
.NET 8 and .NET 10. The initial macOS ARM64 run passed 29 scenarios and exposed
incorrect nonzero process-exit reporting. The following records distinguish
harness adaptation, debugger behavior, and the external runtime correction.

## 1. Original test projects and external builds

Samsung's [test runner](https://github.com/Samsung/netcoredbg/tree/9744e1f051866215611b8440c638042aa2aa2f72/test-suite)
targets `netcoreapp3.1`. Passing `TargetFramework=net8.0` on the CLI did not
retarget every restore/project-reference evaluation: `NETSDK1005` reported missing
framework targets. Passing `TargetFrameworks` too still left referenced projects
building for netcoreapp3.1.

The repository now generates external projects from the original project metadata,
sets the target framework there, disables default compile item discovery, and
adds absolute references to the original `.cs` files. Project references preserve
their relative layout in the generated project tree. Samsung project files,
C# sources, and assertions remain unchanged. SHA-256 records cover the inputs.
Artifacts, SDK selection, intermediate output, and logs live outside the original
source tree. Test-list and transcript decoding use explicit UTF-8, including on
Windows, so the Chinese-path scenario remains intact.

The upstream shell script ends with a summary rather than a failing aggregate
exit code. Its Linux-oriented process cleanup also does not cover every native
runner. `upstream_suite.py` invokes each TestRunner case directly, requires both
exit code zero and the runner's success marker, enforces a timeout, and records
all scenario results. A changed default upstream DAP list blocks release until
its required list is reviewed. The upstream manual-only kill scenario remains
outside that automated list.

## 2. A real failure beyond the previous smoke fixture

`VSCodeTestExitCode` invokes `_exit(3)` on macOS and expects a DAP `exited` event
with code 3. The earlier source-built debugger emitted code 0 on macOS ARM64.
The existing repository fixture exited normally with code 0, so it could not
have detected this defect.

An initial .NET 8 run passed the other 29 scenarios. The first externally linked
.NET 10 candidate also passed the other 29. This is an assertion failure in
actual debugger behavior, not a missing SDK or unsupported test-project format.
The failed scenario stayed in the required gate throughout the investigation.

Samsung's [managed exit callback](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/debugger/managedcallback.cpp)
reads its [waitpid tracker](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/debugger/waitpid.cpp)
on PAL platforms. The upstream executable exports an ELF-style `waitpid` hook.
macOS dynamic symbol binding did not consistently route runtime calls through
that hook.

## 3. External Darwin compatibility and two runtime ABIs

A temporary dyld interposer proved that recording the observed child-exit status
corrected the .NET 8 failure. The production approach links a companion dylib into
the debugger rather than requiring a user environment variable. An external
constructor registers a callback into Samsung's existing synchronized PID tracker.
The observer calls the original wait operation once, preserves `errno`, and only
reports returned exit status. It does not consume another child's wait event.

The CMake overlay removes an executable-only `-force_flat_namespace` switch from
the companion library's directory, since clang rejects that switch with
`-dynamiclib`. It selects two-level namespace binding for the executable and
uses `@rpath` plus `@loader_path` for a relocatable installed package. The original
Samsung CMake files remain unchanged. Apple's
[dyld sources](https://github.com/apple-oss-distributions/dyld) describe the
interposition mechanism on which the external library relies.

The first linked observer fixed .NET 8 but still failed .NET 10. Native symbol
inspection showed that .NET 10.0.11's `libmscordaccore.dylib` imports
`waitpid$NOCANCEL`. Adding a separate observer for that ABI entry point corrected
the .NET 10 result. Targeted runs against the installed companion-library build
then passed `VSCodeTestExitCode` on .NET 8.0.24 and .NET 10.0.11, both returning 3
through DAP without environment injection. Full candidate validation remains
separate from these targeted experiments. The [local evidence archive](cross-platform-2026-09-06/upstream-suite-local/README.md) retains the failed suite result and corrected exit-code transcripts with provenance hashes.

## 4. Release boundary and fault tests

Both source-build validation and extracted-VSIX validation run the required
upstream suite. Aggregation requires exact scenario coverage, correct runtime
and architecture, an unchanged input tree, and the tested debugger's SHA-256.
The publisher repeats the completeness checks before any upload.

`test_gate.py` adds negative cases for a failed scenario, missing scenario,
timeout with a nominal zero exit code, and a suite run against another debugger.
`test_publication.py` runs publication and resume logic with real temporary
manifests and fake GitHub/Open VSX services. It covers partial upload continuation,
finalization-only retry, identical byte skipping, mismatched public bytes,
missing preserved VSIX, and missing runtime-suite evidence. This verifies failure
handling without intentionally breaking a public registry release.

The maintainer policy remains: fail the Actions run, preserve evidence, and let
the maintainer respond through their GitHub notification settings. No automatic
rollback, quarantine state machine, or custom notification server was added.
See the [operating policy review](2026-09-06-publication-recovery-and-rollback.md).

## 5. First native matrix and startup failure

[Candidate run 34028072085](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34028072085), attempt 1, used recipe `ee1443d0d2bc0a76dfbd129e574126d6badfeaa9a55bf7aed861750df4f085f5` and candidate version `2.148.23001`. Seven native targets passed both runtime gates. macOS Intel passed all 30 upstream scenarios on .NET 10, but its earlier .NET 8 repository fixture failed before any checks completed. DAP `configurationDone` returned `0x80004005` after approximately five seconds. No .NET 8 upstream-suite result existed for that target because its prerequisite fixture failed.

Samsung's startup path uses `startupWaitTimeout = 5000 ms` and returns `E_FAIL` if the process-attached condition is not observed by the deadline. The timing is consistent with that path, but the first log alone does not establish why attachment was late or absent. The failure was not converted to a pass or excluded. Aggregation failed and packaging/publication were skipped. A maintainer-driven rerun of failed jobs with runner diagnostics was requested to investigate reproducibility; its outcome is recorded separately.

Attempt 2 reran the failed macOS Intel job without changing the workflow recipe or Samsung source. It passed all eight repository fixture checks and all 30 upstream scenarios on each of .NET 8 and .NET 10. The original 498 Samsung files remained unchanged. The aggregate then accepted the latest evidence for every target and packaging started. This establishes a successful rerun, not the root cause of the first startup failure. The [failed-attempt archive](cross-platform-2026-09-06/candidate-34028072085-attempt1/README.md) remains separate.

## 6. Installed-editor check of the new package

The macOS ARM64 VSIX from run 34028072085 passed an actual installed-extension check in VS Code 1.135.0. Extension activation and seven checks per runtime passed on .NET 8.0.24 and .NET 10.0.11. The installed package's source/run provenance matched the candidate, and every installed debugger file matched the VSIX bytes, including the new Darwin library. The VSIX SHA-256 was `fe196696f3866af53654b76f97d132ba5d5718bf2909ac3c8962e45381b45b4e`. [Editor evidence](cross-platform-2026-09-06/candidate-34028072085-editor/README.md) records the result and test harness separately from the eight-platform extracted-adapter gate.

## 7. Intermittent extracted-VSIX exception stack failure

Attempt 2 passed seven extracted-VSIX targets but failed macOS ARM64's .NET 8 `VSCodeTestUnhandledException` scenario. The other 29 upstream cases and all eight repository fixture checks passed on that target. The debugger stopped on the expected unhandled exception, but returned only runtime and synthetic `Main` frames with line zero and no source. The original test dereferenced the absent source field and failed with `NullReferenceException`. .NET 10 did not run on that target because the preceding runtime gate failed. Publication remained blocked.

Samsung's [stack-trace implementation](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/debugger/manageddebugger.cpp) already makes three attempts to reconstruct source frames from exception details when the top physical frame has no source line. Reading `Exception.StackTrace` involves managed evaluation. The roughly 13-second failing scenario is slower than the roughly 2-second passing cases, but the transcript alone does not establish an evaluation timeout or its cause. No assertion or required test was changed.

Ten local repetitions of the same unchanged scenario, .NET 8.0.24, and debugger bytes from the installed candidate all passed. A single maintainer-driven rerun of the failed CI job with diagnostics was requested after this comparison. The [failed VSIX evidence and local repetition results](cross-platform-2026-09-06/candidate-34028072085-vsix-failure/README.md) retain both observations. A successful rerun establishes a passing validation result; it does not establish that the intermittent behavior was corrected.

For a future recurrence, download the failed job's artifact before rerunning it: extracted-VSIX artifacts use a stable name and overwrite earlier attempts. Preserve `vsix-result.json`, the runtime's `upstream-*-result.json`, and the failing scenario transcript. Compare the tested executable hash, SDK/runtime, and source hashes before comparing behavior. Source-build artifacts include the attempt number and remain distinct.

After `upstream_suite.py` has generated and built the external projects, the following invocation isolates this scenario. Replace the four paths with the recorded native SDK, external build directory, original source tree, and extracted debugger. It is the same TestRunner invocation used by the automated gate.

```sh
"$DOTNET" "$WORK/build/bin/TestRunner/debug/TestRunner.dll" \
  --local "$DEBUGGER" --proto vscode --test VSCodeTestUnhandledException \
  --sources "$SOURCE/test-suite/VSCodeTestUnhandledException/Program.cs" \
  --assembly "$WORK/build/bin/VSCodeTestUnhandledException/debug/VSCodeTestUnhandledException.dll" \
  --dotnet "$DOTNET"
```

Use the matching SDK environment from the full-suite invocation. A diagnostic launcher can append `--engineLogging=<path>` and `--log` to the debugger invocation while forwarding TestRunner's arguments. Local reproduction does not replace the complete native and extracted-VSIX release gates.

Attempt 3 passed both runtime gates on macOS ARM64 without modifying the candidate or test assertions. The final publication preflight accepted all eight packages, and [the complete dry run](cross-platform-2026-09-06/candidate-34028072085-final/README.md) finished successfully. This candidate covers 32 target/runtime/phase combinations, with eight fixture checks and 30 upstream scenarios in each. It did not upload to Open VSX. The subsequent main-branch run records actual publication separately.
