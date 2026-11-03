# F5 retry release evidence

Published version **11.7.18003**, source commit `1d5f543dc86fa5aba6da0c8c2c2f94c2668836c7`, [successful CI run 41602853096](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41602853096). The [release report](../../2026-11-03-file-based-app-retry-release.md) explains the fix and scope.

- `notification-pending-repro.json`: the original-runtime counterexample, including recovery only after notification dismissal.
- `run-summary.json`: all 29 successful jobs and their URLs, including eight native, eight package, and eight extracted-VSIX targets.
- `release-manifest.json` and `validation-manifest.json`: public release provenance, package hashes, and debugger validation records.
- `publication-status.json`: the publisher's successful download/hash checks for all eight Open VSX packages.
- `readback-summary.json`: independent exact-version/latest-feed checks for every platform and the public Windows ARM64 package's complete hash, canonical modules, and debugger payload comparison.
- [editor/](editor/README.md): the unchanged new CI VSIX installed normally, actual compiler-error notification retained during a successful retry, Web SDK conversion, selected-project regression, DAP trace, and process/provenance records.
- `sdk-query-results.json` and [sdk-switch-only/](sdk-switch-only/README.md): separate SDK/property transition observations; the latter uses the unchanged previous `11.7.18002` package to isolate editing from prior failed debug commands.

The independent reader downloaded one public VSIX; the release publisher separately downloaded all eight. The installed-editor tests cover Windows ARM64/VS Code, check the binding, and invoke the registered command. They do not synthesize a physical F5 key or test Cursor. The eight-platform CI matrix establishes debugger protocol/package coverage, not eight-platform editor UI coverage.

The intermittent `MSB3552` and reported editor refresh delays remain separate investigations. Nonfatal post-session transport diagnostics are retained in the editor evidence. Local paths are normalized, and large binaries, caches, and raw editor DOM are omitted. The [public release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r3) retains the full platform artifacts and `native-validation-evidence.zip`.
