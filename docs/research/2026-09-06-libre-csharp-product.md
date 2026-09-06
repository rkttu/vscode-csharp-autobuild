# Conditions for a Libre C# distribution alongside the unmodified build

On September 6, 2026, this review compared the existing unmodified distribution with `muhammad-sammy.csharp` using Open VSX metadata, public workflows, and published platform manifests. The community extension already automates CI builds and publication and provides eight platform VSIX packages. Some published manifests contain platform-to-debugger asset mismatches. [Comparison evidence](libre-csharp-product-2026-09-06/evidence.json)

Subsequent validation: [Windows x64 and ARM64 source builds and .NET 8/10 DAP checks passed](2026-09-06-windows-validation.md). The observations below retain the scope of this earlier research stage.

There are practical grounds to evaluate a separate Libre C# distribution. The relevant criteria are upstream tracking, platform execution tests, redistributable component management, and a limited debugger integration surface. The existing upstream-function-code-preserving distribution should operate independently so failures or delays in the new variant do not block its publication.

The report first compares the roles and current distribution states, then covers support criteria, a companion extension versus an integrated product, component boundaries, and adoption gates. `Libre C#` is a working name in this report; no product or repository was created.

The observations and proposals have the following limits:

> This assessment reflects September 6, 2026. All eight community publication manifests were read, but their VSIX binaries and IDE behavior were not tested. These findings do not prove eight-platform support for the proposed variant or full feature parity with Microsoft's debugger.

## 1. Distinct roles for the unmodified and Libre distributions

The current repository adjusts publisher metadata, distribution notices, and the build environment while preserving upstream functional code. That is the scope of “unmodified” used here. This path provides a baseline for upstream tracking and issue reproduction and can remain independent of the debugger decision. [Current workflow](https://github.com/rkttu/vscode-csharp-autobuild/blob/5cab182e77a8001f35d868c6c96a54a5cb52b45b/.github/workflows/build-and-release.yml)

| Criterion | Current unmodified distribution | Proposed Libre distribution |
| --- | --- | --- |
| Value | Track upstream features and releases | Development and debugging validated with open components |
| Changes | Publication metadata and build environment | Component selection, debugger integration, required compatibility patches |
| Publication gate | Existing automated build policy | Tests for declared platforms and features |
| Update inputs | Upstream tag and SHA | Upstream SHA, debugger, dependencies, and integration revision |
| User selection | Existing extension ID and installation path | Explicit selection of a separate extension ID |

A new variant can avoid overwriting the existing extension or migrating installations automatically. Separate IDs alone do not resolve activation conflicts: the supported user configuration must account for C# language-server and debugger registrations. VS Code rejects multiple descriptor factories for the same debug type. [Extension identity](https://code.visualstudio.com/api/references/extension-manifest), [factory registration](https://code.visualstudio.com/api/references/vscode-api#debug.registerDebugAdapterDescriptorFactory)

## 2. Validation and operations that distinguish the community extension

The inspected default-branch SHA of `free-vscode-csharp` was `d94fae6e1552f1a60eacda933fc76c399b36591f`. Its CI builds on pushes and pull requests; a separate release-triggered workflow publishes to Open VSX. Describing the project as dependent on manual builds would be inaccurate. [CI workflow](https://github.com/muhammadsammy/free-vscode-csharp/blob/d94fae6e1552f1a60eacda933fc76c399b36591f/.github/workflows/ci.yml), [publication workflow](https://github.com/muhammadsammy/free-vscode-csharp/blob/d94fae6e1552f1a60eacda933fc76c399b36591f/.github/workflows/publish.yml)

| Observation | Current unmodified distribution | Community distribution |
| --- | --- | --- |
| Version returned by Open VSX `latest` | `2.148.23` | `2.145.21-g154a82fd27` |
| Publication date in that response | August 7, 2026 | June 27, 2026 |
| Platform downloads for that version | Eight | Eight |
| Debugger selection | Upstream vsdbg | Samsung netcoredbg |

Versions and dates are API snapshots, not evidence of long-term maintenance quality or abandonment. The community project's latest GitHub release tag also differs from its published Open VSX version; this comparison uses the actual publication. [Unmodified distribution API](https://open-vsx.org/api/dotnetdev-kr-custom/csharp/latest), [community distribution API](https://open-vsx.org/api/muhammad-sammy/csharp/latest)

All eight published manifests contain the same debugger dependency list. They assign `netcoredbg-osx-arm64.zip` to both macOS x64 and ARM64, and the conventional Linux amd64 archive to Linux and Alpine x64. No explicit corresponding entries were found for Windows ARM64 or Alpine ARM64. This distinguishes eight downloadable VSIX packages from successful debugging on eight platforms. It is not a reproduced execution failure of those published packages. [Published manifest URLs and mappings](libre-csharp-product-2026-09-06/published-debugger-mapping.json), [source mapping](https://github.com/muhammadsammy/free-vscode-csharp/blob/d94fae6e1552f1a60eacda933fc76c399b36591f/package.json)

A new distribution can connect upstream tracking, debugger builds, and per-target execution tests, then publish the results with each release. That provides users with support evidence beyond a one-time mapping correction. If the community project adopts the same foundation and meets these criteria, the extra benefit of maintaining a separate complete extension decreases. The comparison concerns behavior and operations rather than branding.

## 3. Five dimensions of support coverage

Coverage includes OS and CPU, .NET version, language features, debugging features, and execution environment. Generating eight archives does not establish all of these. The earlier source-build experiment only validated basic DAP on macOS ARM64. [Source-build validation scope](2026-09-06-netcoredbg-source-build.md)

| Dimension | Initial product criteria | Evidence |
| --- | --- | --- |
| OS and CPU | Eight existing VSIX targets, minimum OS and ABI | Binary inspection and native execution per target |
| .NET version | Each declared runtime version | Build and debug the same fixture per version |
| Language features | Project loading, completion, diagnostics, navigation, rename, code fixes | Upstream-derived tests and editor checks |
| Debugging features | Launch, attach, conditional breakpoints, stepping, variables, evaluation, exceptions | DAP regression tests of the packaged debugger |
| Environment | Declared local, ASP.NET Core, remote Linux, and container combinations | Installation and sessions in actual extension hosts |

Razor, Blazor, XAML, Source Link, Hot Reload, legacy .NET Framework, and Mono require explicit support decisions. Removing them would preclude a claim of no feature loss from the current C# extension. If essential, open replacement implementations and tests become part of the product scope. The previous investigation did not establish a replacement for all of C# Dev Kit. [Upstream features](https://github.com/dotnet/vscode-csharp/blob/main/README.md)

Publication policy also affects update latency. A newly detected upstream version can be built immediately while a failed combination remains ineligible for stable publication. The existing distribution can continue under its own policy while the Libre stable variant retains its last passing combination. Validating every platform introduces cost and delay, so immediate upstream publication and a fully tested stable variant cannot be assumed to appear simultaneously.

## 4. Companion debugger extension versus integrated Libre VSIX

A companion debugger extension and an integrated distribution address different requirements. An extension pack can install multiple extensions together, but it does not automatically replace their binaries or executable factories. [Extension manifest](https://code.visualstudio.com/api/references/extension-manifest)

| Design | Requirement addressed | Remaining constraints |
| --- | --- | --- |
| Unmodified C# plus separate debugger extension | Existing language features alongside independent DAP debugging | Separate debug type and configuration; proprietary components in the original remain |
| An installation pack containing both | One installation entry point | Same replacement and integration constraints |
| Separate upstream-based Libre C# VSIX | Remove the proprietary debugger, integrate installation and launch, control components | Integration patches and validation against upstream changes |
| New LSP client and debugger UI | Independent client architecture | Reimplementation and parity testing of existing language features |

A companion extension can experiment with a separate debug type. Overwriting the existing `coreclr` factory from another extension does not fit the public registration API. Modifying the original extension's files after installation would also undermine the unmodified distribution and update reliability. [Registration constraints](https://code.visualstudio.com/api/references/vscode-api#debug.registerDebugAdapterDescriptorFactory)

An integrated VSIX directly addresses a goal that includes consistent installation and F5 behavior without proprietary components. Reusing the upstream client with limited changes is an initial way to preserve language features. The current findings do not justify making a complete LSP client rewrite the default approach.

Follow-up code inspection found that declaring a static executable in the extension manifest lets the current factory use it directly. Basic local integration therefore has a candidate with no TypeScript changes. Dynamic SDK and architecture selection and ancillary capabilities remain separate integration work. [Additional integration findings](2026-09-06-debugger-integration.md#4-packaging-and-debugger-launch-integration-points)

## 5. Independent components and a limited integration layer

The proposed structure separates upstream inputs, debugger packages, and the integration layer. netcoredbg can remain the default engine while paths, arguments, and capabilities are kept behind a limited interface. DAP implementations differ in settings and behavior, so sharing a protocol does not guarantee interchangeable engines. [Current factory](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/src/coreclrDebug/activate.ts)

- **Upstream inputs.** Pin C# and Samsung sources separately. Build Samsung's original files unchanged and record C# changes as purpose-specific patches.
- **Debugger packages.** Provide platform mappings, executables, companion DLLs, hashes, notices, and validation results in an independent manifest.
- **Integration layer.** Manage executable paths, arguments, environment, configuration translation, and feature exposure through a limited interface. Include a validated default engine in the final VSIX.

This structure separates debugger updates from C# source updates without owning a Samsung feature fork. Its build and validation outputs could also be consumed by the community extension. Repository count remains an implementation choice; the existing distribution's extension ID, state, and publication triggers should remain separate from the new product.

A Libre scope also requires examining components beyond the debugger. Upstream distinguishes its MIT-licensed source from the license terms for official distributions, and the current `package.json` license field points to `RuntimeLicenses/license.txt`. Packaging includes NuGet components for Roslyn, Dev Kit integration, XAML tools, and test discovery. Replacing the debugger does not by itself establish redistribution rights for the entire VSIX. [Upstream license explanation](https://github.com/dotnet/vscode-csharp/blob/main/README.md#license), [packaging definitions](https://github.com/dotnet/vscode-csharp/blob/2f5806a9f39575bfaf4ca16445f420440a43e050/tasks/packaging/offlinePackagingTasks.ts#L66)

A new variant can inspect included files and later downloads, then select components under the chosen distribution policy. Removing a component also requires testing its dependent features. Open software authored by Microsoft is not excluded by origin: MIT-licensed Roslyn language-server and dbgshim components remain usable candidates. A complete component-by-component determination is follow-up work. [Roslyn language-server package](https://www.nuget.org/packages/roslyn-language-server/5.11.0-1.26379.6), [dbgshim evidence](netcoredbg-source-build-2026-09-06/evidence.json)

## 6. Conditions for proceeding with a separate product

The findings justify an experimental independent variant. Stable product adoption depends on the following checks, with Windows ARM64 and Alpine behavior among the outstanding priorities. [Source-build assessment](2026-09-06-netcoredbg-source-build.md)

1. Validate netcoredbg source builds and core debugging scenarios on all eight targets.
2. Audit packaged components and automatic downloads, then define the Libre feature set.
3. Validate language features and debugging together in an unpublished VSIX.
4. Apply the same patches and tests to several recent upstream tags, recording patch size and failure causes.
5. Test debugger-only and upstream-only updates, version allocation, and publication stops after failures.
6. Compare maintaining a separate product with the community extension adopting the same build and validation foundation.

If essential features lack open replacements, or every upstream update requires broad changes, the integrated product carries greater maintenance cost. A narrower debugger-build service and companion extension remain options. Conversely, repeatable platform validation with limited integration changes would establish both differentiation and an operating basis for a separate distribution.

## 7. A separate experiment that preserves the existing distribution

A Libre C# variant can be evaluated alongside the current unmodified build. The existing path preserves upstream functionality; the new path can take responsibility for component selection and target-specific tests. Since the community project already automates builds and provides eight VSIX packages, the comparison depends on actual support evidence and update behavior. [Comparison evidence](libre-csharp-product-2026-09-06/evidence.json)

The immediate experiment combines reusable debugger builds and tests with a small integration patch and separate VSIX. Long-term operation depends on repeatedly validating the declared platforms and features. Maintaining the existing distribution and evaluating the new variant can proceed together. This investigation added research and evidence only.
