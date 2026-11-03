# Web bootstrap and FBA snippets release

Date: November 3, 2026. Distribution: `dotnetdev-kr-custom.csharp-with-netcoredbg`.
Publication is being prepared; the expected next version is **11.7.18004**,
packaging revision 4. The release workflow determines the reserved revision and
must complete before availability is claimed.

## Changes

Managed Web file apps use evaluated MSBuild properties and framework references
returned by their existing build invocation. The wrapper reads the source's
`.run.json` or `Properties/launchSettings.json`, applies Project-profile arguments
and environment variables, checks/prepares development HTTPS with consent when
needed, and passes browser readiness handling to VS Code. A missing profile uses
an in-memory development profile with dynamic HTTPS/HTTP ports when endpoint
configuration is absent. Explicit browser opt-out and HTTP-only settings are
respected. Existing selected-project routing and the earlier retry fix remain.

The package adds [21 FBA snippets](../file-based-app-snippets.md) while preserving
the 42 upstream C# snippets. Small patterns adapted from
`dotnetdev-kr/dotnet-fba-examples` retain their source notice and original MIT
license. The package README removes the inherited Dev Kit installation
recommendation; no recommendation-suppression configuration is added.

All new behavior is in repository-owned CommonJS modules, snippet assets, and
checked packaging metadata. This change adds no upstream JS/TypeScript source
rewrites and retains the existing native debugger and language service.

## Pre-publication verification

- 54 focused Node tests and 34 variant Python tests passed.
- The pristine pinned upstream integration preflight passed.
- The local Web package passed 14 real VS Code assertions, including HTTP
  profile args/environment, actual server readiness, endpoint breakpoints and
  stepping, HTTP response, server termination, retry, and selected-project
  regression. A profile-owned external launcher recorder verified the exact
  browser URL handoff without opening browser UI or changing the OS browser.
- The local snippets package passed 21 registered-name insertions, six actual
  SDK 10.0.402 build compositions, and two MSBuild environment/fallback
  evaluations. Existing upstream snippets and debugger/runtime bytes were
  preserved.

The prototype evidence is under
`validation-artifacts/fba-web-local-2026-11-03/` and
`validation-artifacts/fba-snippets-local-2026-11-03/`. Local editor coverage is
Windows ARM64/VS Code 1.144.1. Certificate creation/trust, browser rendering,
physical F5, prefix/Tab UI, Cursor, and cross-platform editor behavior were not
automated. Certificate state/consent/cancellation are tested with mocks.

## Publication gates and limits

The release retains C# `v11.7.18-prerelease` at
`1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at
`9744e1f051866215611b8440c638042aa2aa2f72`. All eight native and extracted-VSIX
targets, package asset checks, and publication readback must pass. Final run,
package hashes, public feed checks and installed-release verification will be
recorded after completion.

Custom Kestrel certificate logic and suppressed/custom lifetime logging can
require application-specific configuration. Development-certificate trust
support depends on the host's .NET/OS trust tooling. This release does not claim
to fix the intermittent home-directory Web SDK `MSB3552`/slow-build report,
Cursor SDK refresh delays, the earlier cancel-during-debugger-start race, or
post-termination transport read diagnostics. MSBuild property-name IntelliSense
remains a separate investigation.
