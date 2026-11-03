# Web bootstrap and FBA snippets release

Date: November 3, 2026. Distribution: `dotnetdev-kr-custom.csharp-with-netcoredbg`.
Version **11.7.18004**, packaging revision 4, is published on
[Open VSX](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg)
and in the [GitHub release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r4).
All 29 CI jobs passed, and independent public readback confirmed all eight
platform-specific exact-version and latest feeds at `11.7.18004`.

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
`validation-artifacts/fba-snippets-local-2026-11-03/`. The normalized
[preserved local evidence](file-based-apps-2026-11-03/web-snippets-evidence/README.md)
includes the actual harnesses, protocol trace, expanded sources and build logs.
Local editor coverage is
Windows ARM64/VS Code 1.144.1. Certificate creation/trust, browser rendering,
physical F5, prefix/Tab UI, Cursor, and cross-platform editor behavior were not
automated. Certificate state/consent/cancellation are tested with mocks.

## Publication gates and limits

The release retains C# `v11.7.18-prerelease` at
`1c27e135b5dada55a240e4a504bafa759ec578e8` and netcoredbg `3.2.0-1092` at
`9744e1f051866215611b8440c638042aa2aa2f72`. All eight native and extracted-VSIX
targets, eight packages, package asset checks and publication readback passed.
The [29-job summary](file-based-apps-2026-11-03/web-snippets-evidence/publication/run-summary.json)
preserves each conclusion and job URL. The matrix covers .NET 8/10 and the
required upstream DAP suites, separately from the Windows ARM64 editor checks.

[Release run 41644074504](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41644074504)
uses source commit `ca5d10d97431181d934369c76c28347fac8a05a6` and selected
`11.7.18004`, revision 4, tag
`csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r4`.
Its fingerprint is `19c236beffbd25959c6f657a693c7eb80edc3ee138cc442f36743dcf28983374`
and recipe is `59f2538af59b1808384ed13a4f1c19cf6392ec0519aa4c5efd970ad93828fcf2`.

GitHub finalization occurred on November 3, 2026 at **23:17 KST**
(`14:17:17 UTC`). The publisher downloaded and hash-verified all eight public
VSIX files before finalizing. The [publication status](file-based-apps-2026-11-03/web-snippets-evidence/publication/publisher-publication-status.json)
records all eight verified targets.

Independent [public readback](file-based-apps-2026-11-03/web-snippets-evidence/publication/readback-summary.json)
confirmed all eight exact-version and platform-specific latest feeds. The
downloaded public Windows ARM64 file matches the actual installed CI artifact's
whole-file hash, so the editor checks below apply to the same public bytes.
Its four owned modules, three snippet/notice/license assets, 42 upstream and
21 FBA snippets, two file templates, and 16 native files match the source and
release validation records. Public manifests and registry metadata accompany
the summary; the generic latest index is retained as informational data.

## Installed CI package verification

The unchanged CI-built Windows ARM64 `11.7.18004` VSIX has SHA-256
`0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5`,
matching the package job's verification record. Two fresh VS Code profiles
installed that actual package and passed all 14 Web/retry/project checks,
21 registered snippet insertions, six representative builds and two MSBuild
environment/fallback evaluations. The [preserved evidence](file-based-apps-2026-11-03/web-snippets-evidence/README.md)
distinguishes this CI package from both earlier local overlays.

All four owned modules and three snippet/notice/license assets match canonical
Git bytes at `ca5d10d`, and all installed files match the archive. The 42 original
C# snippets remain intact. The original compiled C# entry retains SHA-256
`b9b22a4523458d4f5e8763e87f84b4cc3c3a60be0321a01fef10c0cb445aecea`.
The freshly rebuilt native executable has SHA-256
`29addd991c76cccc31e0cb58414ed3f5dce533842f63e58443ef4188861ad769`;
all 16 native files match this run's validation manifest. The native source pin
is unchanged; rebuilt native bytes are checked against this run's manifest,
rather than assuming they equal an older build.

All test editor/extension-host/debuggee/URL-recorder processes terminated.
The Web trace retains three nonfatal transport read diagnostics after normal
session termination; this release does not claim to fix them. The editor scope
remains Windows ARM64/VS Code API commands and HTTP/URL handoff, not actual
browser rendering, certificate installation, physical keys or Cursor.

Custom Kestrel certificate logic and suppressed/custom lifetime logging can
require application-specific configuration. Development-certificate trust
support depends on the host's .NET/OS trust tooling. This release does not claim
to fix the intermittent home-directory Web SDK `MSB3552`/slow-build report,
Cursor SDK refresh delays, the earlier cancel-during-debugger-start race, or
post-termination transport read diagnostics. MSBuild property-name IntelliSense
remains a separate investigation.
