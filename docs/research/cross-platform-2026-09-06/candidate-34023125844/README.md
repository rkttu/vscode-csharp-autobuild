# Revised candidate evidence

[Run 34023125844](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34023125844)
completed successfully at recipe commit `4b0b41ea198014a6384ff513e4ab660a8125bb8a`.
It produced candidate `2.148.23001` with the warm brown musical-staff icon.
`candidate-matrix.json` records the exact version policy and source identities.

`summary.json` records the eight native targets, sixteen source-build runtime
combinations, eight VSIX targets and sixteen extracted-adapter combinations.
`validation-manifest.json` preserves native archive and payload hashes.
`release-manifest.json` preserves all eight final VSIX hashes. `run.json` and
`jobs.json` show the successful final dry run and skipped registry upload.
The `native` and `vsix` directories contain the corresponding per-target records
and DAP traces. No binaries or registry credentials are committed here.

The installed-editor check reused the previously documented isolated
[VS Code harness and procedure](../editor-smoke/README.md). The harness code
was unchanged. It installed this run's `darwin-arm64` VSIX version `2.148.23001`
over the earlier temporary test installation, then launched the actual editor
with the same isolated user-data, extension and workspace directories.
VS Code 1.135.0, the copied .NET runtime extension 3.1.0 and native SDKs
8.0.418/10.0.400 remained the test inputs.

The editor exited with code 0. `editor-smoke/ide-result.json` confirms the new
extension version, activation and both successful runtime sessions. The two
adjacent traces came from VS Code's debug-adapter tracker. The actual installed
VSIX hash matches the runner's `vsix/darwin-arm64/vsix-result.json` record.
Its icon matches `assets/netcoredbg/icon.png` byte for byte.

`archive-provenance.json` records original and archived hashes. Text is UTF-8
without BOM and uses LF line endings. Personal SDK roots in editor JSON are
normalized to `/local/dotnet`; GitHub runner paths remain unchanged.
The harness here validates real extension-host activation and local launch,
not manual visual acceptance, VSCodium, full language-service behavior, attach,
remote debugging or complete Microsoft debugger feature parity.
