# File-based debugging stability contract

Status: qualification policy defined for [#14](https://github.com/rkttu/vscode-csharp-autobuild/issues/14), November 4, 2026. Required VSCodium targets are **not yet qualified** by this document. [#15](https://github.com/rkttu/vscode-csharp-autobuild/issues/15) owns installed-editor measurement, numeric budgets and gate implementation; [#21](https://github.com/rkttu/vscode-csharp-autobuild/issues/21) owns release qualification.

This policy applies to `dotnetdev-kr-custom.csharp-with-netcoredbg`. It defines the evidence needed to call everyday FBA workflows stable. It does not change runtime behavior, current publication gates or the independent upstream-preserving distribution. The [stabilization epic](https://github.com/rkttu/vscode-csharp-autobuild/issues/13) tracks implementation.

## Support targets and current evidence

| Combination | Current evidence | Qualification status |
| --- | --- | --- |
| Eight native VSIX targets, .NET 8/10 | Source-built and extracted-VSIX debugger/DAP release gates; see [pinned inputs](../config/netcoredbg.json) | Existing debugger coverage; not an editor/FBA qualification |
| Native macOS ARM64 VSCodium, stable .NET 10 | User reports and separate historical macOS VS Code checks | Required editor target; installed VSCodium qualification pending |
| Native Windows ARM64 VSCodium, stable .NET 10 | [Installed Web lifecycle](research/web-lifecycle-2026-11-05/README.md), [compiler-failure/concurrent-retry](research/build-failure-retry-2026-11-05/README.md), and [direct-runtime graceful-disposal](research/graceful-disposal-2026-11-06/README.md) controls | Partial evidence with distinct invocation routes; required qualification matrix, actual host shutdown and physical F5 pending |
| Windows ARM64 VS Code 1.144.1 | Retained installed FBA API-command tests; later local diagnostic prototype | Comparison control; not evidence for native F5 input or VSCodium |
| Windows ARM64 SDK 10.0.403/runtime 10.0.14 | Local CLI phase measurements below | CLI control only; no editor/debugger qualification |
| .NET 11 RC3, macOS ARM64 VSCodium | Reported CLI build success and a user-confirmed Slim HTTPS source correction | Exploratory; no stable-baseline claim |
| Other editors/architectures | Only the evidence explicitly recorded for their combinations | No additional editor qualification implied |

The initial stable editor targets use a supported, serviced .NET 10 SDK with the editor, SDK and debugger architectures matching. A run must pin exact versions; a floating `latest` selection is not a recorded baseline. Existing native gate SDK pins and the application SDK selected by a source directory are separate inputs.

Before a qualifying run, record OS/build, native architecture, editor version/channel/hash, VSIX version/hash/build ID, actual loaded extension directory/identity, upstream C# and Roslyn revisions, dotnet executable/root, SDK selected from the source directory, application runtime and language-server runtime. An installed-version display alone does not identify loaded code. SDK selection and the language-server runtime are not required to have the same version.

## Required workflow scenarios

These are target behaviors. Pending issue links identify work that has not yet been certified.

| ID | Scenario | Required result |
| --- | --- | --- |
| S01 | Cold activation, saved Console file, no folder | Launch captured source, bind a breakpoint, inspect/evaluate/step, print expected output and exit; no user project or launch file needed |
| S02 | Edit the same file and run again | New saved content and expected values are used; output/session state does not leak between cycles |
| S03 | Dirty file, save or save cancellation | Save before classification/build; a cancelled/failed save starts no build and the next valid attempt works |
| S04 | Compiler failure followed by correction | Report the failure and retry in the same window while the previous notification remains open |
| S05 | Console → Web → Console and SDK/property directive edits | Language-service context and build use the saved source; no unexplained manual reset; [#17](https://github.com/rkttu/vscode-csharp-autobuild/issues/17) |
| S06 | Full and Slim Web hosts, HTTP and explicit HTTPS profiles | HTTP readiness and response are real; explicit HTTPS retains its intended configuration/consent; browser opt-out and actual readiness are respected; [#20](https://github.com/rkttu/vscode-csharp-autobuild/issues/20) |
| S07 | Folder windows, included/excluded files, multiple projects | Classification respects evaluated Compile items and explicit FBA markers; the existing selected project remains selected when appropriate |
| S08 | F5, Run/Start Debugging menu and direct command | Record each entry path separately; supported paths launch the intended file; user keybinding overrides and active-session Continue retain precedence; parity work is [#16](https://github.com/rkttu/vscode-csharp-autobuild/issues/16) |
| S09 | Change global.json or installed SDK intentionally | Record the new selected toolchain and refresh outcome; compare CLI and language-server state; any required explicit reset is documented, bounded and tested |
| S10 | Repeated F5, cancellation and concurrent separate files | Coalesce the same in-progress operation, preserve unrelated sessions and permit retry after cancellation; no late-started abandoned session; [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) |
| S11 | Fresh install and version A → B update | Normally install distinct versions, apply the editor's update/reload flow and verify the actual loaded identity/files; [#19](https://github.com/rkttu/vscode-csharp-autobuild/issues/19) |
| S12 | Stop, normal exit, launch failure and host reload | Clean up owned processes, ports and output safely; preserve unrelated paths and retain evidence if cleanup fails |

Use native GUI input for a claim about actual F5, and menu interaction for a menu claim. A command API call is separate evidence. If CI cannot generate native input reliably, attach an explicit manual check with exact versions and outcome. Never infer physical-key coverage from manifest inspection or `executeCommand`.

Interactive stdin, Native AOT debugging, Hot Reload, remote debugging and broad IDE parity are outside this qualification scope. They cannot be counted as failing baseline cases or silently advertised by a passing baseline run.

## Repeatability protocol

For every required scenario and target, use two independently created editor profiles. Each profile runs ten consecutive cycles. For ordinary editing scenarios, use one cold editor activation and nine warm cycles in that same window. Scenarios that intentionally install/change an SDK, apply an extension update or reload the host (S09/S11/S12) may perform the resets specified in their steps; record each as a planned action and record the resulting host/cache state rather than describing every later run as a warm host. A cold editor profile does not imply an empty SDK/NuGet cache; record editor, SDK, restore and OS-cache conditions separately. Do not purge user caches to manufacture a pass.

A cycle includes the scenario's action and assertion, breakpoint or server-response evidence where applicable, Stop/exit or expected failure, owned-resource cleanup and readiness for the next attempt. Capture the first failure. A later successful retry does not erase that failure or restart the consecutive-pass count without an investigation record. Intentional negative cases pass only when their expected failure and same-window recovery both occur.

Ordinary editing, build failure, cancellation and retry must not require a window restart, language-server restart or reinstall. An explicit extension update can require the editor's documented reload; an SDK installation/change can have an explicit reset procedure. Record these planned actions separately from workarounds for unexplained failures. The allowed reset paths do not excuse S02–S08 failures during normal source editing.

Ten cycles in two profiles is an initial regression threshold, not a statistical reliability guarantee. Any adjustment must be recorded with a reason before qualification; lowering it after observing a failure is not a passing result.

## Phase measurements and budget activation

Use a monotonic clock for elapsed durations and UTC timestamps for correlation. Record every phase's start/end and outcome, including failed attempts. Do not combine different fixture, input route, editor, cache or network conditions into one unlabelled percentile. User decision time in certificate prompts is recorded separately from machine execution.

| Phase | Start → end | Budget status / owner |
| --- | --- | --- |
| Activation | Editor invokes activation → owned commands and required upstream services ready | VSCodium calibration pending, #15 |
| SDK selection | Resolve toolchain → version/architecture information available | CLI control measured; VSCodium calibration pending, #15 |
| Classification | Source captured → file/project/error decision, including all candidate evaluations | Limited CLI control measured; project-heavy/editor calibration pending, #15 |
| Restore/build | Build process starts → exit and required output/metadata verified | CLI control measured; network restore and editor calibration pending, #15 |
| Debugger readiness | Debug request → initialized/breakpoint-bound or explicit terminal failure | Unmeasured, #15; a true startDebugging return alone is insufficient |
| Web readiness | Process launch → reported listening address and expected HTTP response | CLI and limited installed VSCodium HTTP controls measured; calibration pending, #15 |
| Cleanup/retry readiness | Stop/exit/failure/cancel → owned resources released and next command accepted | Limited installed Stop/build-failure/retry and direct-runtime disposal controls measured; full failure/cancellation matrix pending, #15/#18 |
| Context refresh | Saved directive/project/SDK change → matching language-service context | Unmeasured in required targets, #15/#17 |

For each required target and fixture, #15 must first collect cold/warm samples and failures, then propose numeric phase deadlines with the measurement record and a rationale. Review and version the accepted budget values before enabling a qualification gate. Missing measurements or an unset budget mean **not qualified**, never pass or zero latency. A budget breach preserves the elapsed duration, last phase and first-failure log and requires investigation.

Separate local/offline fixture budgets from network restore and interactive certificate work. Bound a complete phase as well as each child process. PR #26 adds a shared five-minute cooperative cancellation deadline for noninteractive preparation, including sequential project evaluations. Save, cleanup, interactive certificate work and debugger handoff/session lifetime remain outside that deadline; calibrated budgets and their qualification still belong to #18 and #15.

### Initial CLI control measurements

The [measurement record](stability/2026-11-04-cli-calibration.json) contains eight SDK/build/application observations across two fixtures on Windows ARM64, SDK 10.0.403/runtime 10.0.14. Each fixture has one first run and three warm runs, in an isolated CLI home/AppData/NuGet configuration with package sources disabled. This is **not** the ten-cycle/two-editor-profile qualification protocol.

The record includes fixture, harness and used-module hashes plus OS/Node provenance. It remains an initial CLI control dataset, not an implementation of the complete qualification evidence schema: installed-editor observations, accepted budgets and editor first-failure logs remain absent.

| CLI control phase | Console: first / warm range (ms) | Slim Web: first / warm range (ms) |
| --- | --- | --- |
| SDK version query | 129.21 / 107.06–125.83 | 117.31 / 109.37–134.09 |
| Classification | 6.97 / 0.46–0.99 | 0.02 / 0.02–0.04 |
| Managed build | 1982.41 / 735.15–778.19 | 2077.48 / 926.31–1068.23 |
| CLI application | 69.96 / 58.80–65.46 | 313.45 / 258.42–271.59 |

Console classification searched ancestors and found no candidate project; the Web directive selected FBA immediately. These samples do not measure MSBuild project membership cost. Console application timing includes process exit; Web application timing includes HTTP 200 validation and stopping the owned process. Neither measures debugger handoff or language-server refresh. No numeric VSCodium deadline is inferred from these controls.

## Failure classification and ownership

| Classification | Required action and owner | Qualification effect |
| --- | --- | --- |
| Package-owned defect | Maintainer reproduces/fixes routing, lifecycle, defaults, installation diagnostics or packaging and adds a regression | Blocks affected required baseline |
| Upstream defect | Maintainer records the reproducer, exact upstream versions, impact and tracking/recovery; distinguish evidence from hypotheses | Blocks an affected required baseline until fixed or the baseline is explicitly revised with evidence |
| Application/configuration error | Report the failing stage and required application correction; test the corrected app and preserve intentional negative-case behavior | An expected, actionable failure can pass its negative case; broken positive fixtures cannot |
| Documented limitation / exploratory combination | State the unsupported behavior and exact boundary; keep preview results separate | Does not extend support or erase baseline failures |
| Unknown / intermittent | Keep open with first-failure evidence, attempted recovery and next investigation | No green rerun or “by design” closure without an explained boundary |

HTTPS opt-in for a Slim host is an application requirement. A package injecting HTTPS without knowing host capability is package-owned behavior to examine. CLI compilation, language-server load, adapter startup and application startup are separate stages, not interchangeable success/failure signals.

Severity: P0 for data loss, modification outside owned paths or unsafe secret/trust handling; P1 for an affected required workflow failure, hang, stale-source launch or unexplained restart/reinstall; P2 for bounded exploratory-only failures or diagnosed non-blocking defects. The maintainer records disposition and evidence. Ownership describes the next action, not blame or an automatic support exemption.

## Evidence and release decision

Each run records:

- Run ID/time, fixture/source/profile hashes, OS/editor/SDK/runtime pins and exact candidate VSIX hash/build ID.
- Loaded identity/path, separate installed metadata and registry result, upstream C#/Roslyn identity, actual dotnet executable/root and source-directory SDK selection.
- Profile ID, iteration 0–9, cold/warm/cache/network state and invocation route (native input, menu or command API).
- Per-phase monotonic timings, budget version/status, expected and observed result, breakpoint/output/HTTP assertions, exit outcome and owned-resource cleanup.
- First-failure logs, any planned reset, unexpected recovery and linked defect. Sanitize personal paths, environment values and secrets without removing diagnostic structure.

Schema examples and collection implementation belong to #15. Source pin changes require a new recorded candidate; a local same-version prototype is not public-release evidence. Attach all required baseline results and the existing eight-platform native/extracted-VSIX results to the same candidate bytes. [#21](https://github.com/rkttu/vscode-csharp-autobuild/issues/21) may qualify a release only after every required scenario has evidence, budgets have been calibrated, and no unresolved baseline blocker remains. Preview-only defects retain their own status and recovery notes.

Issue #14 delivers this policy and its explicit pending-calibration boundary. It does not certify VSCodium, enable a new gate or publish a stabilization release. Normal installation/update and public-readback checks remain required in #19/#21.
