# Installed baseline SDK transition check

This check uses the unchanged public **11.7.18002 Windows ARM64** VSIX, not the retry-fix candidate. It isolates SDK editing from prior failed F5 commands: open a plain C# file, edit/save the same document to add `#:sdk Microsoft.NET.Sdk.Web` and WebApplication code, wait for language-service recovery, then invoke its first registered F5 command.

The real VS Code 1.144.1 host with SDK 10.0.402 observed a transient `CS0103` and then recovery at 3.52 seconds. The first command started in 3.39 seconds, hit the source breakpoint, exposed a WebApplication local, printed the framework type, and exited normally.

- `editor-result.json`: language-service hover/diagnostic timeline, command registration, debugger checks, and result.
- `provenance.json`: exact public VSIX hash and installed-file comparisons, SDK/editor identity, and limits.
- `extension-test.cjs`: the editor test harness; only a separate empty driver was a development extension.
- `editor.dap.jsonl`: actual adapter protocol trace.
- `launch-metadata.json` and `process-exit.json`: isolated host launch and normal exit.

The test checks the contributed F5 binding and invokes its command through the editor API. It does not synthesize a physical keypress, read raw context keys, or test Cursor. The small fixture does not reproduce the user's SDK 11 RC1/home-directory environment or complete HTTP/PInvoke source. Local paths are normalized; binaries and caches are omitted. This result leaves the reported post-edit failure unconfirmed outside that user environment.
