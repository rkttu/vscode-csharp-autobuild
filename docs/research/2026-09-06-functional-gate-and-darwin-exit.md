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
source tree.

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
separate from these targeted experiments.

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
