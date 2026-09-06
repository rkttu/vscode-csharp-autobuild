# Installed VSIX editor-host validation

The test used the actual `darwin-arm64` VSIX from candidate run 34021654129,
version 0.1.4000. `provenance.json` records its SHA-256, editor version, native
host and dependency extension version. `ide-result.json` records activation and
the two successful launch sessions. The DAP traces come from VS Code's debug
adapter tracker, so they include editor-generated configuration requests too.

The test used a separate temporary `--user-data-dir` and `--extensions-dir`.
The existing `ms-dotnettools.vscode-dotnet-runtime` 3.1.0 installation was copied
into that isolated extension directory. The candidate VSIX was installed with
`code --install-extension` using the same directories. Normal editor settings
and extensions were not changed.

To reproduce the layout, copy `test.cjs` to `<temporary-root>/harness/test.cjs`
and give that directory a minimal development-extension `package.json` with
publisher `local-research`, name `netcoredbg-research-harness`, version `0.0.1`
and engine `vscode: ^1.106.0`. Copy `scripts/validation/fixture` into
`<temporary-root>/workspace/net8` and `net10`. Set each fixture's `global.json`
to the pinned SDK from `config/netcoredbg.json` and build `Probe.csproj` into
`output` with the matching `ValidationTargetFramework=net8.0` or `net10.0`.

The editor was launched with `--extensionDevelopmentPath` pointing to `harness`,
`--extensionTestsPath` pointing to `harness/test.cjs`, and `workspace` as its
folder argument. `DOTNET_ROOT`, `PATH`, the isolated
`omnisharp.dotNetCliPaths` setting and `dotnetAcquisitionExtension.existingDotnetPath`
pointed to the native SDK installation. The .NET acquisition entry used extension
ID `dotnetdev-kr-custom.csharp-with-netcoredbg`. The inherited
`ELECTRON_RUN_AS_NODE` variable was removed only from the test editor process.
The app's `CFBundleExecutable` supplied the executable name (`Code`).

The runner resolved its exported `run()` promise successfully and the test
editor exited with code 0. The test exercised the real extension host and debug
API; it did not perform manual visual acceptance, language-service feature
testing, VSCodium testing, attach or remote debugging. Personal SDK roots in the
archived JSON are normalized, with original and archived hashes retained.

The runner follows VS Code's documented
[extension-test entry points](https://github.com/microsoft/vscode-docs/blob/main/api/working-with-extensions/testing-extension.md).
