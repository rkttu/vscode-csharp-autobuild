# Web file-based app launch bootstrap

Research date: November 3, 2026. Distribution baseline: `dotnetdev-kr-custom.csharp-with-netcoredbg` 11.7.18003; C# source `1c27e135b5dada55a240e4a504bafa759ec578e8`; netcoredbg source `9744e1f051866215611b8440c638042aa2aa2f72`. The investigation below led to an isolated local Web prototype described at the end. It is not a published release. Automated verification does not create or trust certificates.

## Finding

Project-like ASP.NET Core startup can be added in the repository-owned FBA wrapper without another upstream source rewrite. It needs three distinct pieces: apply a development launch profile, prepare a certificate when HTTPS is selected, and open the browser after the server reports a listening address. The current explicit managed-DLL launch bypasses SDK `dotnet run` launch-profile processing, so that processing must be added deliberately.

The existing C# configuration provider already offers a local Windows/macOS development-certificate flow. VS Code's built-in `serverReadyAction` handles browser opening independently of the debugger implementation. Netcoredbg emits the DAP output events that this feature consumes.

## Recognize the application and its launch intent

Use evaluated MSBuild properties from the same SDK, source directory and build properties as the FBA build: `UsingMicrosoftNETSdkWeb`, `UsingMicrosoftNETSdkRazor`, `UsingMicrosoftNETSdkWorker`, `OutputType`, `TargetFrameworkIdentifier`, and `TargetPlatformIdentifier`. `FrameworkReference` is an item and requires `-getItem`, not `-getProperty`. The [Web SDK sets its server identity and ASP.NET framework reference](https://github.com/dotnet/sdk/blob/v10.0.100/src/WebSdk/Web/Targets/Sdk.Server.props); the [MSBuild evaluation API](https://learn.microsoft.com/en-us/visualstudio/msbuild/evaluate-items-and-properties) can expose those values.

A Web SDK marker alone is insufficient for every policy. Razor libraries and workers need different behavior, gRPC profiles often disable browser launch, and browser/WebAssembly targets are outside the current managed `coreclr` flow. A custom SDK can also inherit Web SDK behavior without a literal Web directive in the source. Prefer evaluated identity plus launch-profile intent and actual server readiness over source-text matching alone.

Avoid doubling expensive project evaluation for this feature. If metadata is returned by the build invocation, ensure a build target is explicitly requested: a property/item query without a target can be evaluation-only. A separate metadata query also repeats Web SDK default-item globbing, relevant to the already reported slow home-directory build.

## Apply launch profiles

File-based apps support a source-adjacent `sample.run.json` for `sample.cs` from .NET 10.0.100. A conventional `Properties/launchSettings.json` takes precedence when both exist, with a warning. The checked .NET 10 source supports Project profiles; .NET 11 RC1 also supports Executable profiles. Executable and IIS Express profiles should not silently be treated as the current managed-DLL launch. Sources: [.NET 10 file lookup](https://github.com/dotnet/sdk/blob/v10.0.100/src/Cli/dotnet/Commands/Run/RunCommand.cs#L253), [.NET 10 profile selection](https://github.com/dotnet/sdk/blob/v10.0.100/src/Cli/dotnet/Commands/Run/LaunchSettings/LaunchSettingsManager.cs#L25), [.NET 11 profile model](https://github.com/dotnet/sdk/blob/v11.0.100-rc.1.26425.128/src/Microsoft.DotNet.ProjectTools/LaunchSettings/LaunchSettings.cs#L15).

Profile lookup must use the original source basename, not `FileApp`, the managed output assembly name selected by the current wrapper.

Honor `environmentVariables`, `applicationUrl`, `commandLineArgs`, `launchBrowser`, and `launchUrl`, including JSON comments/trailing commas supported by the SDK. The SDK maps `applicationUrl` to `ASPNETCORE_URLS` and then applies explicit environment variables, allowing a profile's explicit same-name value to take precedence. Browser launch is parsed as profile data but is not performed by the checked CLI `dotnet run` implementation. Sources: [application of profile values](https://github.com/dotnet/sdk/blob/v10.0.100/src/Cli/dotnet/Commands/Run/RunCommand.cs#L184), [launch-profile model](https://github.com/dotnet/sdk/blob/v10.0.100/src/Cli/dotnet/Commands/Run/LaunchSettings/ProjectLaunchSettingsProvider.cs).

The latest Learn documentation describes `DOTNET_LAUNCH_PROFILE` as a selector. In the checked 10.0.100, 10.0.402 and 11 RC1 source it is an output environment value identifying the selected profile, not the input selector. For parity with these pinned versions, use explicit profile selection or their first supported profile behavior rather than assuming that environment variable selects a profile.

For the requested zero-project F5 experience, the extension can synthesize an in-memory development profile when no profile file exists. This preserves the absence of a user-maintained project or launch.json. Defaults for Development environment, HTTP/HTTPS endpoints and browser launch would be extension policy, not behavior implied by the SDK name. Existing user profiles, explicit `launchBrowser=false`, and application endpoint configuration must take precedence.

## Open the browser when the server is ready

Add the built-in action to the programmatic launch object:

```json
{
  "serverReadyAction": {
    "action": "openExternally",
    "pattern": "\\bNow listening on:\\s+(https?://\\S+)"
  },
  "checkForDevCert": false
}
```

This example uses the wrapper's certificate policy instead of the upstream helper. The browser should open once after the actual HTTP or HTTPS listening message, using the selected profile's relative or absolute `launchUrl` when supplied. A build finishing is not proof that the server is listening. Suppressed/custom-formatted lifetime logging can require another readiness mechanism.

VS Code's [built-in readiness handler](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/extensions/debug-server-ready/src/extension.ts#L344) watches debugger `output` events and provides a [common debug configuration contribution](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/extensions/debug-server-ready/package.json#L34). The [netcoredbg DAP implementation](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/protocols/vscodeprotocol.cpp#L329) emits compatible stdout/stderr events. Current FBA launches use `internalConsole`, matching the [documented C# browser-launch mechanism](https://code.visualstudio.com/docs/csharp/debugger-settings#_starting-a-web-browser).

Merely passing `launchBrowser`, `launchSettingsProfile`, or `launchSettingsFilePath` to netcoredbg is insufficient. Its [launch handler](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/src/protocols/vscodeprotocol.cpp#L585) consumes the program, args, environment, working directory and debugger options, not those Microsoft-adapter profile facilities. Resolve the profile in the owned wrapper and pass its concrete values.

## Prepare HTTPS deliberately

Web SDK selection does not create an HTTPS endpoint. Since .NET 7, [Kestrel's implicit HTTPS binding was removed](https://learn.microsoft.com/en-us/aspnet/core/breaking-changes/7/https-binding-kestrel). An HTTPS development profile must specify HTTPS URLs or the application must configure them. Template-generated port ranges are chosen when templates create profile files, not discovered as free ports on each run.

When the chosen profile needs HTTPS:

1. Check certificate validity and trust with `dotnet dev-certs https --check --trust`.
2. If setup is needed, use `dotnet dev-certs https --trust` through the normal user-visible trust flow. It can generate the missing development certificate and establish trust.
3. Continue, cancellation, and setup failure must produce clear outcomes. Do not clear or replace existing certificates as a routine launch step.

The [.NET 10 check path](https://github.com/dotnet/aspnetcore/blob/v10.0.0/src/Tools/dotnet-dev-certs/src/Program.cs#L300) is noninteractive and does not create/trust certificates. The [trust path](https://github.com/dotnet/aspnetcore/blob/v10.0.0/src/Tools/dotnet-dev-certs/src/Program.cs#L395) can show Windows confirmation or macOS Keychain prompts. Linux support depends on its trust tooling and browser stores and can report partial trust; it needs platform-specific handling rather than an assumption of identical setup everywhere.

The pinned C# [configuration provider](https://github.com/dotnet/vscode-csharp/blob/1c27e135b5dada55a240e4a504bafa759ec578e8/src/shared/configurationProvider.ts#L133) defaults `checkForDevCert` to true whenever a coreclr configuration has `serverReadyAction`, even for HTTP. Therefore HTTP launches should explicitly set it false. An HTTPS launch can reuse the existing local Windows/macOS flow by setting it true. That flow is skipped for Linux, remote/web contexts and pipe transport.

The existing [certificate helper](https://github.com/dotnet/vscode-csharp/blob/1c27e135b5dada55a240e4a504bafa759ec578e8/src/utils/dotnetDevCertsHttps.ts#L11) invokes PATH's dotnet with the extension host's current directory/environment, rather than the wrapper's selected executable and source directory. Reusing it requires checking that those selections agree; a dedicated wrapper path can instead use the already selected SDK consistently, with `checkForDevCert=false` to prevent duplicate handling.

The production FBA wrapper does not set `DOTNET_GENERATE_ASPNET_CERTIFICATE=false`. That setting appears in isolated test launchers and controls CLI first-use generation, not the explicit certificate setup commands above.

## Proposed implementation sequence

First add profile resolution and Web-server metadata detection to the owned wrapper. Apply environment, arguments and endpoint policy, then perform HTTPS setup only when that selected policy requests it. Finally add server readiness/browser opening to the existing coreclr launch, preserving non-Web FBA behavior and the existing selected-project branch.

A complete verification should cover HTTP/HTTPS, trusted/missing/untrusted certificates, user cancellation, startup/build failure, explicit browser opt-out, custom ports and launch paths, multiple simultaneous apps, and SDK selection through global.json. The browser must not open on failed startup or before readiness.

## Local prototype

The requested local prototype adds [`web.cjs`](../../scripts/variant/file-based-apps/web.cjs) and integrates it into the existing owned runtime. SDK 10.0.402 probes verified that `build` with `-target:Build`, `-getProperty` and `-getItem` returns both real DLL/PDB outputs and Web metadata in one invocation. Exit status is checked before consuming metadata because failed builds can return JSON too.

The local VSIX uses the public Windows ARM64 `11.7.18003` package as its base, replaces owned runtime modules, and removes the inherited README Dev Kit installation recommendation. All original compiled C# extension and native debugger entries remain byte-identical. The display name includes **LOCAL WEB TEST**; the retained version is not a new registry release.

Its manual workspace includes no-profile HTTPS, an HTTP profile that opens `/health`, explicit browser opt-out, and a console app. HTTPS creation/trust is left to the user's explicit first-F5 consent flow. All 54 focused Node tests and 33 variant Python tests passed. Certificate cases and browser-ready configuration are exercised with mocks in focused tests.

The final unchanged VSIX has SHA-256 `6a390dcaf06b6b803b6b76a4d758b40c911a523afbb06daffda998b19786fc8d`. It passed 14 actual editor checks covering real source/build metadata, run.json environment/arguments, listening output, endpoint breakpoints/locals/stepping, HTTP response, termination, retry after a compiler failure, and existing selected-project debugging. With an owned URL recorder configured only in the test profile's `workbench.externalBrowser`, the built-in `serverReadyAction` invoked that external launcher with the exact expected `/probe?via=ready` URL after readiness. Browser opt-out produced no launcher invocation. This verifies the browser launch handoff, not real browser rendering or real TLS/certificate installation. Physical F5, Cursor, and cross-platform editor coverage remain outside these automated checks. The intermittent home-directory Web SDK `MSB3552`/slow-build observation remains separate.

Known limits include custom Kestrel certificate/configuration logic that cannot be inferred from launch settings, the interval between releasing a selected port and Kestrel binding it, and the pre-existing cancellation race while `startDebugging` is already in progress. Profile environment values support ambient `%NAME%` expansion; command-line arguments remain structured strings without shell expansion. Three nonfatal transport `read error` diagnostics after normal session termination remain in the editor evidence; this prototype does not claim to fix them.

Build inputs, package hashes, metadata probe logs, and editor evidence are under `validation-artifacts/fba-web-local-2026-11-03/`. These local artifacts are not release evidence for eight-platform publication.
