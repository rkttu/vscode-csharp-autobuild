# Installed first-release package in VS Code

The macOS ARM64 VSIX built by main run 34031151621 passed activation and seven checks per runtime in VS Code 1.135.0 with .NET 8.0.24 and .NET 10.0.11. Every installed debugger file matched its VSIX entry, and the installed provenance matched the main run and merge commit. The test used isolated user, extension, and workspace directories.

The VSIX SHA-256 is `5051f72839d07e518ef60fba6c64add0794a73e242ec92de7eeae97beefb780c`. Registry publication is verified separately. The [same test harness](../../candidate-34028072085-editor/test.cjs) was used. Paths are normalized; raw and archived result hashes are retained.
