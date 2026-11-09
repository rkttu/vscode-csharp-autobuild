# Native F5 series control

This prospective workflow prepares one candidate ZIP and controls two independently created profiles, `r01` and `r02`, with ten consecutive inputs each. It extends the [single-profile manual guide](manual-f5-validation.md). Synthetic tests exercise the tooling; **no actual native/manual series or qualification run is established by this change**. A successful series remains one Windows ARM64 VSCodium, stable .NET 10, no-folder Slim HTTP Web control, with `qualification: false`.

The [controller](../scripts/variant/lifecycle/series.py) never sends a key. Select `manual-native` or `native-injected` before planning. Human declarations remain separate from renderer, build, session, breakpoint, HTTP and resource evidence. The [stability contract](stability-contract.md), all original #18 criteria, pending AC1/4/6 decisions, macOS, menu/Continue precedence, rapid duplicate-F5 coalescing, LSP/context/HTTPS, calibration, #45 and release work remain open.

## Freeze a new series

Use a reviewed, clean source checkout and a nonexistent artifact directory. Keep it outside the source checkout or in an ignored artifact location; the controller does not stash or change source files. Retain every earlier failed series. Do not clear its markers, substitute a replacement profile or switch mechanisms after an attempt.

Create an input JSON file outside the new series directory. The following is a schema template, not an executable set of pins. Replace all placeholders with actual absolute paths, lowercase SHA-256 pins and exact outputs. `executables.*.version` is the stripped stdout from the selected Python/Node `--version` or PowerShell `$PSVersionTable.PSVersion.ToString()`. The plan observes and checks these outputs and hashes; later stages verify the frozen file bytes.

```json
{
  "schema": 1,
  "preparation": {
    "baseVsix": "<absolute base VSIX path>",
    "baseSha256": "<64 lowercase hexadecimal characters>",
    "runtimeVsix": "<absolute vscode-dotnet-runtime 3.2.0 VSIX path>",
    "runtimeSha256": "<64 lowercase hexadecimal characters>",
    "editor": "<absolute native ARM64 VSCodium executable>",
    "editorCli": "<absolute matching VSCodium CLI>",
    "dotnet": "<absolute native ARM64 dotnet executable>",
    "sdkVersion": "<exact stable 10.0.xxx SDK>"
  },
  "executables": {
    "python": { "path": "<absolute Python executable>", "version": "<exact stdout>" },
    "node": { "path": "<absolute Node executable>", "version": "<exact stdout>" },
    "powershell": { "path": "<absolute PowerShell executable>", "version": "<exact stdout>" }
  },
  "nativeF5Input": "manual-native",
  "launcherDeadlineSeconds": 2400,
  "conditions": {
    "editorProfile": "<planned fresh profile conditions>",
    "sdkCache": "<existing SDK/cache conditions>",
    "nugetCache": "<per-profile NuGet conditions>",
    "restore": "<restore conditions>",
    "osCache": "<shared OS cache conditions>",
    "network": "<network conditions>",
    "operator": "<operator and input procedure>"
  },
  "declaredMetadata": {
    "osBuild": "<recorded OS/build reference>",
    "nativeArchitecture": "<recorded architecture reference>",
    "editorChannel": "<channel reference>",
    "applicationRuntime": "<application runtime reference>",
    "languageServerRuntime": "<language-server runtime reference>",
    "upstreamCsharp": "<upstream C# revision reference>",
    "upstreamRoslyn": "<upstream Roslyn revision reference>"
  }
}
```

`conditions` and `declaredMetadata` are operator declarations, not independently detected facts. Unknown or unsupported metadata does not qualify a target. Preserve the underlying inventories/readbacks and distinguish the application SDK from the language-server runtime. A fresh editor profile does not imply cold SDK or OS caches. The existing preparer isolates editor, extension, appdata, dotnet-home and NuGet directories and clears package sources; language-service/offline restore diagnostics may still occur.

From that source checkout, invoke the controller using the same Python executable selected in the config:

```powershell
$python = '<the pinned Python executable>'
$series = (Resolve-Path './scripts/variant/lifecycle/series.py').Path
$root = '<absolute nonexistent series artifact directory>'
$config = '<absolute completed input JSON file>'
& $python -B $series plan --root $root --config $config
```

Planning records the source and harness identities, executable/VSIX/editor inputs and version outputs. It builds `candidate.vsix` once, publishes its pinned `candidate-manifest.json` and freezes `series-plan.json` before any profile preparation. JSON originals and staged `.tmp` copies are retained; these are not a complete portable runtime or operating-system archive.

## Prepare and run the first profile

```powershell
& $python -B $series prepare --root $root --profile r01
& $python -B $series run --root $root --profile r01
```

Preparation validates the manifest, current source, native target, package/build identity and every uncompressed candidate entry. It exclusively copies the same ZIP bytes into `r01/local-lifecycle.vsix`; it does not build a second archive or patch already published expected metadata. A validation rejection leaves no candidate output; an actual I/O failure retains any partial copy as evidence. Existing directories/files cannot be reused or overwritten.

`run` normally installs the candidate and dependency into the isolated profile and displays its test window. It waits for the existing driver; it is not a key producer. Prepare the operator procedure and second terminal before starting it. The driver retains its 90-second phase guard. The optional whole-launch cap defaults to 2,400 seconds in this series, within the launcher's 60..3,600 range. Thirty-second version/helper and manual-wrapper settlement caps are additional tooling safety limits; they neither pause the driver nor establish calibrated qualification budgets.

For **manual mode**, personally perform the observation and one-key procedure in the [manual guide](manual-f5-validation.md) for each live request. Immediately record it through this series wrapper, rather than calling the receipt helper directly:

```powershell
& $python -B $series manual-input --root $root --profile r01 --sequence 1 `
    --observer '<human observer ID>' `
    --observed-window-title '<actual title personally observed>' `
    --note '<actual source/focus and one-key observation>' --confirm-human-f5
```

Only the person who actually observed the matching window/editor and pressed exactly one F5 may confirm this declaration. Repeat with the next sequence only after its new request appears. The wrapper invokes the pinned staged receipt helper; it sends no key and provides no independent hardware proof. Helper refusal, incomplete publication or another attempted-stage failure stops the series. Never press again because a helper failed or because the outcome is uncertain. In injected mode, a separately prepared native-input producer and original observations/receipts are still required; the manual wrapper cannot be used as a fallback.

For a failed or uncertain human observation, stop without input and report it explicitly:

```powershell
& $python -B $series stop --root $root --reason '<actual failure or uncertainty>'
```

The controller cannot independently detect an unreported human observation failure. A reported failure is retained at series level and closes the active profile's canonical input marker without overwriting existing evidence. The driver observes that marker and rejects further work through its existing failure/owned-session cleanup path. This does not guarantee instantaneous cancellation of an OS event or uncooperative process already in flight.

## Gate the second profile and inspect the result

The first run must pass full evidence validation before the controller permits **preparation** of `r02`, not merely before its launch:

```powershell
& $python -B $series prepare --root $root --profile r02
& $python -B $series run --root $root --profile r02
& $python -B $series verify --root $root
```

Use `--profile r02` for its manual input declarations. It has a new profile, source copy, nonce and requests, while its installed candidate comes from the exact same frozen ZIP. Ordinary cycles stay in the same window: one cold editor activation and nine warm cycles per profile. Do not reload, reinstall or reset caches to obtain a passing cycle.

Success requires complete launcher and driver results, ten ordered requests/receipts and distinct sessions/tokens/outputs, exact saved/dirty fixture revisions, raw renderer/build evidence, source breakpoint/evaluation, HTTP nonce/revision/PID and the separate termination/PID-exit/port-rebind/output/terminal-queue observations. Cleanup observations carry their own times and base paths; they are not an atomic guarantee that resources remain absent indefinitely. An exit code, a receipt or a successful-looking partial result alone is insufficient.

Inspect `*-attempt.json`, `*-result.json`, logs, original driver data and `first-failure.json` together. A partial failure marker or retained lock represents stopped or unresolved work, not permission to delete the marker and continue. Preserve partial originals. The aggregate is published only after both profiles pass; any applicable failure prevents a green result. Read-only `verify` reports a validated snapshot and does not guarantee that no event occurs after its final check.

Even an actual passing series supplies only this control's target, fixture and recorded assertions. No actual series was run for this implementation. The full stability matrix, calibrated budgets and independent macOS, menu/project/context/HTTPS/cancellation/concurrency and release gates remain required.
