# Cross-platform validation and the independent netcoredbg release pipeline

On September 6, 2026, this repository built Samsung netcoredbg 3.2.0-1092 for all eight C# extension targets, generated eight independent VSIX packages, and passed .NET 8/10 DAP checks before and after packaging. The Alpine packages include repository-owned hosting compatibility code while preserving the original Samsung files. The final publication check passed in dry-run mode. No new extension has been published. [Complete candidate run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34021654129)

This report covers the independent extension identity, Open VSX prerequisites, icon choice, native results, Alpine compatibility work, and release gates. It distinguishes implemented automation from successful execution and from publication.

The discussion starts with publication and branding decisions, then records platform evidence and the unresolved runtime boundary. The final sections describe the connected workflows and the remaining release conditions.

The observations have the following scope:

> Checked on September 6, 2026. The research branch has not been merged into the default branch. Candidate 0.1.4000 passed all eight native source-build targets, eight VSIX builds, sixteen extracted-adapter runtime combinations, and the final dry-run gate. Local VS Code 1.135.0 also activated the installed macOS ARM64 VSIX and passed launch checks on both runtimes. Open VSX upload and recovery remain unexecuted.

## 1. Independent identity under the existing namespace

The selected display name is **C# (with netcoredbg)**. Its extension ID is `dotnetdev-kr-custom.csharp-with-netcoredbg`. The existing `dotnetdev-kr-custom.csharp` distribution keeps its current workflow, source policy and state file. The identity is configured in [variant.json](../../config/variant.json).

Open VSX requires a publisher agreement, a namespace and an authorized access token. Its publishing guide explicitly permits one token to publish multiple extensions. It does not prescribe a separate advance registration for every new extension name: the first VSIX publication creates that extension under the package's `publisher` and `name`. Existing namespace access can therefore support the new extension without creating another namespace. [Official publishing procedure](https://github.com/eclipse-openvsx/openvsx/wiki/Publishing-Extensions)

The public API currently identifies `rkttu` as the publisher of the existing `csharp` version 2.148.23. The proposed neutral extension ID returned HTTP 404. These observations establish current publication state, not a reservation of the new ID or proof that the stored CI token is still valid. Namespace ownership verification and registry scanning are separate from per-extension registration. [Existing extension metadata](https://open-vsx.org/api/dotnetdev-kr-custom/csharp/linux-x64/latest), [namespace access](https://github.com/eclipse-openvsx/openvsx/wiki/Namespace-Access)

The publisher remains responsible for the licenses and redistribution rights of the actual contents. netcoredbg's MIT license does not relicense the language server, XAML tools or other components retained from the original C# package. [Open VSX legal FAQ](https://www.eclipse.org/legal/open-vsx-registry-faq/)

## 2. A distinct icon without corporate affiliation cues

The current C# manifest uses `images/csharpIcon.png`, the purple C# hexagon. No alternate extension icon was found in that upstream source snapshot. The new variant instead uses the independently generated [icon.png](../../assets/netcoredbg/icon.png): a charcoal rounded square with C# lettering, an amber breakpoint and a stepping arrow. The asset is stored in this repository and the overlay copies it into each VSIX. [Upstream manifest](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/package.json), [asset notes](../../assets/netcoredbg/README.md)

The icon and display name avoid Samsung's wordmark, oval logo and Tizen marks. The source attribution remains in the README, build provenance and bundled notices. The README identifies the community publisher and states that Microsoft and Samsung do not publish or endorse this package. This separates a factual dependency attribution from a suggestion of official sponsorship.

The design also avoids altering Microsoft's existing product icon. An MIT source-code license alone is not a basis for assuming unrestricted rights to product branding. Microsoft's published guidance treats product icons and other brand assets separately from factual text references. This report does not determine the licensing status of every individual C# artwork asset. [Microsoft trademark and brand guidance](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks)

## 3. Native execution results for all eight targets

The successful complete candidate run used Samsung commit `9744e1f051866215611b8440c638042aa2aa2f72`, CoreCLR input commit `60629d14374c56f1cb51819049ad1fa529307f8d`, SDKs 8.0.418 and 10.0.400, and DbgShim 10.0.731102. The test processes reported .NET 8.0.24 and .NET 10.0.11. These are pinned test inputs and observed runtimes, not assertions about the latest servicing releases. [Build configuration](../../config/netcoredbg.json), [archived results](cross-platform-2026-09-06/summary.json), [successful aggregate](cross-platform-2026-09-06/candidate-34021654129/validation-manifest.json)

| Target | Native host | Source build | .NET 8 DAP | .NET 10 DAP |
| --- | --- | --- | --- | --- |
| `win32-x64` | Windows Server 2022 x64 | Passed | Passed | Passed |
| `win32-arm64` | Windows 11 ARM64 | Passed | Passed | Passed |
| `linux-x64` | Ubuntu 22.04 x64 | Passed | Passed | Passed |
| `linux-arm64` | Ubuntu 22.04 ARM64 | Passed | Passed | Passed |
| `darwin-x64` | macOS 15 Intel | Passed | Passed | Passed |
| `darwin-arm64` | macOS 15 ARM64 | Passed | Passed | Passed |
| `alpine-x64` | Alpine 3.22.1 container on native x64 | Passed with external build and hosting compatibility | Passed | Passed |
| `alpine-arm64` | Alpine 3.22.1 container on native ARM64 | Passed with external build and hosting compatibility | Passed | Passed |

Each passing runtime combination completed eight checks: conditional breakpoint, stack, variables, evaluation, stepping, post-await breakpoint, exception information and expected output with clean termination. All sixteen required runtime combinations passed in the final native matrix, and the same sixteen combinations passed again using the adapters extracted from the eight VSIX files. The earlier build-only matrix passed twelve combinations and failed Alpine; its evidence remains archived separately. The unchanged-source audit covered all 498 tracked Samsung input files on all eight targets. Generated files and the separate CoreCLR input tree are outside that file-preservation audit. [Validation scripts](../../scripts/validation/README.md)

The matrix describes concrete runner and container configurations. It does not establish compatibility with every older OS version, every Linux distribution, .NET 9 or .NET 11 Preview, remote sessions, attach, integrated terminals or full vsdbg/C# Dev Kit behavior. [GitHub runner definitions](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

## 4. Alpine build fixes and the remaining hosting crash

Alpine exposed three packaging and compilation differences before runtime testing:

- C++ `NULL` definition: musl's `nullptr` definition conflicts with upstream casts to integer metadata tokens. An external force-included header supplies Clang's GNU null constant after the relevant system headers.
- `strerror_r` signature: musl keeps the POSIX integer return type under `_GNU_SOURCE`, while the upstream file selects its GNU pointer-return branch. An external CMake include applies `-U_GNU_SOURCE -D_POSIX_C_SOURCE=200809L` to that one compilation unit, selecting its existing POSIX implementation.
- ARM64 native dependency selection: the `netstandard2.0` managed publish selected the glibc ARM64 dbgshim despite the musl RID. The recipe now copies the exact native asset from the pinned `Microsoft.Diagnostics.DbgShim.linux-musl-arm64` package and records its package and native hashes.

These adjustments preserve the original Samsung files. They add maintenance responsibilities to the external build recipe, including a compatibility header, a per-file compiler setting and exact RID asset selection. The source-preservation claim therefore does not mean that every platform builds with identical default settings. [musl NULL definition](https://git.musl-libc.org/cgit/musl/tree/include/stddef.h), [external inputs](../../scripts/validation/musl-compat.cmake)

After those fixes, Alpine x64 and ARM64 still crashed with process exit `-11` (`SIGSEGV`) on both runtime families. Core dumps show `ManagedCallback::CreateProcessW` calling `Interop::Init`, followed by `coreclr_initialize` inside the installed runtime. This is consistent with the independently reported musl hosting/stack-initialization failure in dotnet/runtime #103741. The downloaded runtime libraries were stripped, so the exact internal crashing CoreCLR function was not symbolized in this run. [Crash diagnosis](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34020443441), [runtime issue and maintainer discussion](https://github.com/dotnet/runtime/issues/103741)

The diagnostic workflow's green status means that it successfully collected evidence. Its four DAP result files still report failure. It cannot promote debugger binaries or trigger publication.

The maintainer subsequently authorized an external runtime hosting experiment while retaining the original-file audit. The repository-owned `musl-coreclr-host.cpp` uses a linker wrapper for the executable's `dlsym` calls. Only the `coreclr_initialize` symbol is redirected, and initialization runs synchronously on an owned pthread with an 8 MiB stack. Other symbol lookups pass through. The caller waits for completion and receives the original status and output arguments. The code does not change CLR environment variables. This extends the maintenance boundary from build settings to runtime hosting behavior and applies only to Alpine. Its independent MIT notice and source accompany the debugger package. [Compatibility source](../../scripts/validation/musl-coreclr-host.cpp)

An Alpine-only workflow mode tests this change on both native CPUs. That mode never produces the complete release gate. The eight-target matrix and the extracted-VSIX tests remain mandatory before publication.

The first [external hosting run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34021312326) at `9a1271a943503b9dc012594ad7963f7630cde7c2` passed both native Alpine builds and all four .NET 8/10 combinations. Each combination completed the same eight DAP checks. All 498 original files remained unchanged on both CPUs. The aggregate job was intentionally skipped because this run covered only Alpine. This confirms the workaround for the recorded fixture and runtimes, without establishing arbitrary hosting configurations or full debugger parity.

The subsequent [complete candidate run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34021654129) at `0c0cc76ecda64d6092fb79179d65baa841f60588` passed all eight native targets and all sixteen runtime combinations. Its [aggregate manifest](cross-platform-2026-09-06/candidate-34021654129/validation-manifest.json) records success for every target and no errors. This result includes the compatibility code and its bundled repository notice.

## 5. Connected validation and publication gates

The new workflows are separate from `build-and-release.yml`. Their flow is:

```mermaid
flowchart LR
    Tags[Samsung tags and latest C# tag] --> Build[Eight native debugger builds]
    Build --> Gate[Complete evidence and hash gate]
    Gate --> VSIX[Eight independent VSIX packages]
    VSIX --> Test[Identity and bundled-adapter DAP checks]
    Test --> Release[Preserve release assets]
    Release --> OpenVSX[Publish and read back all targets]
```

`release-netcoredbg.yml` polls every six hours after default-branch activation. It reads Git tags, including tags without a GitHub release, starting at the configured baseline. It dereferences annotated tags, rejects a moved baseline tag, and compares source and recipe fingerprints with completed variant releases. New C# tags select the last successfully published debugger while newly detected debugger tags remain candidates. A run processes up to sixteen candidates; a failing candidate does not hide newer tags. This initial implementation rebuilds the debugger for C#-only changes as well. Reusing a previously validated engine across those changes remains an optimization. [Detector](../../scripts/variant/discover.py), [workflow](../../.github/workflows/release-netcoredbg.yml)

The aggregate rejects a missing platform, failed runtime, wrong commit/run identity, changed source audit, unexpected native file set or mismatched package hash. Matrix failure, cancellation or skipping also blocks progression. Successful archives contain the same files that the native tests inspected; packaging does not perform another debugger build. [Aggregate gate](../../scripts/validation/aggregate.py), [reusable native workflow](../../.github/workflows/validate-netcoredbg.yml)

The C# overlay changes the extension identity, a small set of hard-coded identity lookups, the debugger descriptor/factory and offline packaging. It assigns the independent version after upstream Git-version calculation, then checks the version again inside the VSIX. It removes the Microsoft debugger dependency mappings and advertises only the `coreclr` debug type. The activation overlay also removes registrations for undeclared debugger types, which VS Code rejects at registration time. The isolated activation test invokes the actual modified entry point and checks it against the manifest. The factory retains SDK-derived `DOTNET_ROOT` handling and rejects a Windows/macOS SDK CPU that differs from the bundled debugger. [Overlay](../../scripts/variant/overlay.py)

The package checks verify the icon, publisher, name, version, VSIX target, executable permissions and every debugger payload hash. Native jobs then rerun the DAP fixture using the adapter extracted from that VSIX. A separate isolated test invokes the actual modified factory with stubbed VS Code/SDK services. These are package and adapter integration checks; they do not execute a full IDE user interface. [VSIX verifier](../../scripts/variant/verify-vsix.py), [factory test](../../scripts/variant/test-factory.cjs)

## 6. Publication state and remaining conditions

Public release jobs run only on `main` after the preceding gates pass. Research-branch manual runs use a dry run; the temporary research push trigger was removed after the successful candidate run. The publisher preserves all VSIX files, debugger ZIPs, manifests and native evidence in a separate draft GitHub release before Open VSX uploads. It uses `csharp-netcoredbg-v...` tags and `--latest=false`, protecting the existing workflow's release names and Latest marker. The new version uses its own `0.1` prefix and a scheduler-run-based numeric patch component. [Candidate workflow](../../.github/workflows/netcoredbg-candidate.yml), [publisher](../../scripts/variant/publish.py)

Open VSX uploads are not atomic across targets. The publisher compares an already present platform's downloaded VSIX hash instead of accepting any duplicate silently. It marks the GitHub release complete only after all eight readbacks match. The detector can select a draft left by an interrupted upload and restore its preserved version, bytes and evidence instead of rebuilding. A draft whose GitHub assets never finished uploading still requires recovery of its missing assets. The real publication and interrupted-upload recovery paths have not been exercised against the registry. [Recovery helper](../../scripts/variant/resume.py), [Open VSX API](https://github.com/eclipse-openvsx/openvsx/wiki/Registry-API)

Local checks passed nine aggregate tests, six detector/recovery-selection tests, isolated activation/factory tests and upstream `npm run compile` (TypeScript, ESLint, localization and Razor grammar generation). An initial overlay smoke used explicitly synthetic validation metadata. The subsequent real candidate used the complete native manifest and produced eight hash-verified VSIX files. Workflow syntax passed actionlint. The earlier failed candidate independently demonstrated that Alpine failure skips packaging, VSIX tests and publication. The final candidate passed the dry-run publication gate, with its actual upload step skipped. [Final job steps](cross-platform-2026-09-06/candidate-34021654129/jobs.json), [release manifest](cross-platform-2026-09-06/candidate-34021654129/release-manifest.json)

The actual macOS ARM64 VSIX was also installed into a separate temporary extension directory and activated in VS Code 1.135.0. The real extension-host test passed .NET 8 and .NET 10 launch sessions, conditional breakpoints, stack and variable inspection, evaluation, stepping, post-await breakpoints and clean termination. The installed bytes match the candidate VSIX hash. This establishes editor integration on that one host; it does not establish VSCodium behavior or a complete language-service/UX acceptance test. [Editor result and provenance](cross-platform-2026-09-06/editor-smoke/ide-result.json), [test source](cross-platform-2026-09-06/editor-smoke/test.cjs)

The branch now has an executed eight-platform candidate pipeline and a successful local editor launch test. The remaining operational step is default-branch adoption and the first registry publication. Attach, remote debugging, integrated terminals, wider runtime coverage and interrupted-upload recovery still require separate validation. No registry write, default-branch merge or change to the existing extension's production workflow has occurred.
