# Published F5 release evidence

Version **11.7.18002**, release source commit `10b0e9ec62227567521dea0ef8a0d4d212eebedd`, [successful run 41587850063](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41587850063). See the [release record](../../2026-11-03-file-based-app-release.md) for the initial cancelled run and the Windows checkout correction.

- `run-summary.json`: all 29 successful jobs, including eight native, eight package, and eight extracted-VSIX jobs.
- `release-manifest.json` and `validation-manifest.json`: public GitHub release manifests, connecting source inputs, recipe, platform payloads, and complete VSIX hashes.
- `publication-status.json`: the publisher's successful download/hash checks for all eight Open VSX targets.
- `readback-summary.json`: independent exact-version and platform-specific latest-feed checks, plus the public ARM64 VSIX download, canonical Git module comparisons, and debugger payload verification.
- `editor/`: the unchanged CI-built VSIX installed in a separate extensions directory, ten real-editor assertions, source harness, protocol trace, provenance, launch metadata, and process-exit verification. Only an empty driver was loaded as a development extension; the target C# extension was installed normally.

The independent readback downloaded one public VSIX (Windows ARM64). The release publisher separately downloaded and hash-verified all eight targets. The editor test is Windows ARM64 only and invokes the exact contributed command, while checking its F5 binding. Native and extracted-VSIX CI cover debugger protocol behavior on all eight targets, not every editor UI or fork. The transport read diagnostic after FBA termination is retained in the editor result; it did not prevent the subsequent project session or normal process exits.

Local paths in the copied editor/readback results are normalized. Large binaries and caches are omitted. The [public release](https://github.com/rkttu/vscode-csharp-autobuild/releases/tag/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r2) retains all eight VSIX files, eight debugger archives, and `native-validation-evidence.zip` with the full build/test evidence.
