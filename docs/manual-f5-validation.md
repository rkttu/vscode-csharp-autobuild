# Manual native F5 validation

This prospective guide describes a human-attested input mode for the existing native F5 lifecycle control. The manual receipt feature has unit verification; **no actual human manual F5 run or new native observation is recorded by this change**. A receipt is the named human's declaration, not independent proof of a hardware keypress or a passing debug workflow.

The [stability contract](stability-contract.md) permits an explicit manual check when native input cannot be generated reliably. Its qualification requirements remain unchanged. This runner currently targets native Windows ARM64 VSCodium with a pinned, stable .NET 10 SDK; native macOS is not implemented here. The fixture is one no-folder HTTP Slim Web file. The [preparer](../scripts/variant/lifecycle/prepare.py), [launcher](../scripts/variant/lifecycle/run.ps1), [driver](../scripts/variant/lifecycle/extension-test.cjs) and [receipt module](../scripts/variant/lifecycle/native-f5-input.cjs) define the implemented checks.

1. **Freeze the plan and inputs before launching anything.** Record the source commit and harness hashes, OS/build and native architecture, VSCodium version/channel/commit and executable/CLI hashes, base VSIX version/hash, runtime-extension VSIX version/hash, candidate ZIP hash/build ID and actual loaded extension identity. Pin the absolute dotnet executable/root and hash, exact stable .NET 10 SDK selected from the source directory, application runtime and language-server runtime, and upstream C#/Roslyn revisions. Pin the Python, Node and PowerShell executable paths, versions and hashes as execution inputs. Record editor/profile, SDK, NuGet, restore and OS-cache conditions separately; a fresh editor profile does not mean an empty SDK cache.

   Choose a new, nonexistent work directory. Never reuse a prepared, attempted or failed directory, and never delete its markers to make it appear fresh. The preparer creates one local candidate and one isolated profile. Keep previous failures and their source/candidate identities separate.

   The following PowerShell example prepares **two inputs in one profile as an initial control only**. Replace every placeholder with a frozen absolute path or exact pin. Run it from the intended repository checkout; do not use a floating SDK selection or a placeholder hash.

   ```powershell
   $repo = (Resolve-Path '.').Path
   $python = '<absolute pinned Python executable>'
   $node = '<absolute pinned Node executable>'
   $powershell = '<absolute pinned PowerShell executable>'
   $baseVsix = '<absolute pinned base VSIX path>'
   $baseSha256 = '<base VSIX SHA-256: 64 lowercase hexadecimal characters>'
   $runtimeVsix = '<absolute pinned vscode-dotnet-runtime 3.2.0 VSIX path>'
   $runtimeSha256 = '<runtime VSIX SHA-256: 64 lowercase hexadecimal characters>'
   $editor = '<absolute pinned native ARM64 VSCodium executable>'
   $editorCli = '<absolute pinned VSCodium CLI path>'
   $dotnet = '<absolute pinned native ARM64 dotnet executable>'
   $sdkVersion = '<exact stable .NET 10 SDK version>'
   $work = '<absolute new work directory for this control>'

   & $python -B (Join-Path $repo 'scripts/variant/lifecycle/prepare.py') `
       --base-vsix $baseVsix --base-sha256 $baseSha256 `
       --runtime-vsix $runtimeVsix --runtime-sha256 $runtimeSha256 `
       --editor $editor --editor-cli $editorCli `
       --dotnet $dotnet --sdk-version $sdkVersion `
       --scenario native-f5 --native-f5-input manual-native `
       --cycles 2 --work-dir $work
   ```

   `--native-f5-input` is valid only with `--scenario native-f5`. Omitting it preserves `native-injected`; select `manual-native` prospectively rather than changing a profile after an automation failure. Both modes allow 2..10 inputs. There is no dynamic input-mode fallback.

   After successful preparation, retain `expected.json`, the candidate ZIP and its recorded SHA-256/build ID, and the plan with all pins before launch. Confirm that `expected.nativeF5.inputMode` is `manual-native`, its cycles and unique window title match the plan, and its staged helper is `WORK/driver/native-f5-input.cjs` with the recorded harness hash. An installed-version display alone will not establish the loaded candidate identity.

2. **Prepare the human's receipt command before starting the editor.** Keep a second terminal ready with the same pinned `$node` and exact `$work` values. Copy the template below into a text buffer first. Fill the sequence, actual complete window title and actual observation note when that request occurs; do not execute it in advance. The observer ID names the human who will personally observe and press the key.

   ```powershell
   # Template only. Execute after personally observing and pressing one F5.
   & $node (Join-Path $work 'driver/native-f5-input.cjs') `
       --work-dir $work --sequence 1 --observer observer-1 `
       --observed-window-title '<actual complete OS window title personally seen>' `
       --note '<actual C# editor focus, source and single F5 observation>' `
       --confirm-human-f5
   ```

   Only the human who actually saw the matching window and C# editor focus and personally pressed exactly one native F5 may execute `--confirm-human-f5`. An agent must not confirm on the human's behalf, infer a keypress from readiness, or invent an observation note. Do not substitute a command API, menu command, automation input, or an earlier keypress.

   The unchanged **90-second input/observation phase** includes the human observation, keypress, receipt publication and ensuing driver assertions. The request expiry does not pause the enclosing phase, which starts before request publication and can close first. Prepare the terminal in advance; do not extend or pause timers or change assertions to accommodate an operator delay.

3. **Launch the prepared profile visibly once.** Use the frozen launcher and its normal installation path. For example, the optional 2,400-second editor-process lifetime cap is within the existing 60..3,600-second range; the default remains 300 seconds.

   ```powershell
   & $powershell -NoLogo -NoProfile -File `
       (Join-Path $repo 'scripts/variant/lifecycle/run.ps1') `
       -WorkDir $work -DeadlineSeconds 2400 -ShowWindow
   ```

   This outer cap starts after the editor is launched and does not bound pre-editor installation/setup or uncooperative OS I/O. It is a test safety ceiling, not a calibrated product deadline. It neither extends a 90-second phase nor guarantees that every phase can consume its full allowance. Do not change launcher security flags, clear caches, reload/reinstall, or switch input modes to obtain a pass after failure.

4. **For each published request, observe, press once, then attest.** Wait for `needs-f5-input-01.json` and the matching armed state in `progress/state.json`. Compare the current request's nonce, sequence, launch token, source and window title with the prepared profile. Before input, check that `f5-input-closed.json` is absent, `progress/state.json` has no `firstFailure`, and the request is still live. If the state is closed, expired, uncertain or failed, stop without sending input or publishing a receipt.

   Personally inspect the visible OS window. Its actual title must contain the unique request title. Verify that the intended `WORK/workspace/a.cs` C# editor has keyboard focus, the window has no workspace folder, and no active debug session would turn F5 into Continue. Click the correct editor if needed, observe focus, and personally press **one F5 exactly once**. Then immediately run the staged helper with the actual title and note for that sequence, while the request and enclosing phase remain open.

   The helper sends no key, launches no application and creates no passing result. It validates the frozen manual mode, helper hash, request hash, source, sequence, armed state, absence of first failure/closure, expiry and unused evidence paths before publishing a receipt. It requires recorded candidate identity fields and a local candidate path; the driver's installed-candidate checks provide separate identity evidence. It cannot establish whether the human declaration is true. Its `actor.type` is `human`, `tool` is `human-observer`, and `evidenceKind` is `human-attestation`; it records one declared keypress with automation and target-command API use set to false. `attestedAtUtc` is the helper's declaration time, **not a measured keypress time**. Do not fabricate `inputAtUtc`, an OS `windowId`, a `sky.press_key` result or other automation measurements.

   The helper retains `manual-observation-01.json`, `manual-action-01.json` and `f5-input-action-01.json.tmp` as immutable originals, then publishes the matching `f5-input-action-01.json` receipt without replacement. Partial files remain if publication fails. A receipt-publication message means only that the attestation was published. Never edit, replace or retry partial evidence to manufacture a completed input.

5. **Let the driver decide the cycle outcome.** The receipt does not relax the existing runtime checks: exactly one renderer F5 dispatch to the owned command, one file-debug build and exact owned session, source breakpoint/evaluation `marker == 40`, HTTP response `value == 42` with the owned nonce and expected revision, then exact-session Stop and PID/port/output/terminal-queue cleanup. Post-start DAP Continue and Stop APIs remain separately recorded driver actions; they do not supply startup-key evidence.

   The first source is saved `initial`. Only after exact cleanup does the driver prepare the next unsaved `retry-f5-N` revision and publish its request. For the example's second input, use `--sequence 2` and a fresh actual observation note after personally repeating the observation and single-key step. Do not manually save the dirty repeat or edit the fixture. Each later input must demonstrate its own save event and new content. Session IDs, launch nonces and output paths must remain distinct; operating-system PIDs may be reused sequentially.

   Stop the series at the first failed preparation, launch, observation, helper publication or driver assertion. Missing readiness, an expired phase, an uncertain/double keypress or a helper refusal is not permission to press again. Preserve the complete work directory, original logs/trace, request/receipt/partial files, elapsed times and first-failure records, together with the human's actual account. Do not prepare a second profile after that failure, restart a consecutive count, rerun the same work directory or hide the failure behind a later success. Any investigated future series needs a separate prospective plan and new directory.

The full contract still requires **two independently created profiles with ten consecutive cycles each**, the same target candidate ZIP and pins within the planned series, and the first-failure protocol. The two-input example does not satisfy that plan. Use the separate [native F5 series workflow](f5-series-validation.md) to build one candidate, copy its exact bytes to independent profiles and gate the second preparation on complete first-profile evidence. Invoking this single-profile preparer twice without the pinned reuse option does not prove same-ZIP reuse. The series tooling is prospective infrastructure; actual recorded execution and the remaining qualification gates are still required.

Actual AC7 completion, policy decisions for AC1/4/6, native macOS, menu parity, rapid duplicate F5, active-session Continue/keybinding precedence, LSP/context health, HTTPS, calibration, [#45](https://github.com/rkttu/vscode-csharp-autobuild/issues/45) and release qualification remain open. A future successful manual control would establish only its explicitly recorded target, fixture, inputs and assertions; it would not close [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) or qualify the full matrix.
