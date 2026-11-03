# Installed CI package retry check

The unchanged **11.7.18003 Windows ARM64** VSIX from [CI run 41602853096](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41602853096) was installed normally into an isolated extension directory. Only a separate empty driver was loaded as a development extension; the target extension and debugger were not injected or modified.

- `editor-result.json`: ten assertions covering actual compiler failure, corrected-source retry, breakpoints/locals/stepping/output/exit, same-file Web SDK conversion, and selected-project regression.
- `notification-observation.json`: the real compile-failure notification remains visible after failure and after retry starts; zero notification-dismiss commands were issued. Only boolean observations from the owned editor's renderer DOM are retained.
- `compile-failure.txt`: actual `CS0246` diagnostics from the first F5 build.
- `provenance.json`: CI source/artifact identity, VSIX SHA-256 matching the package job, installed/archive comparisons, and canonical Git module comparisons. The outer artifact ZIP digest is separately identified.
- `extension-test.cjs` and `editor.dap.jsonl`: harness and actual protocol trace for the three successful debug sessions.
- `launch-metadata.json` and `process-exit.json`: isolated hidden host launch and normal exit.

The host was VS Code 1.144.1 on Windows ARM64 with SDK 10.0.402/runtime 10.0.13. The test checks the F5 binding and calls its registered command; it does not send a physical F5 key or test Cursor. No user manual-test instance was changed. Two nonfatal transport read diagnostics after session termination remain in the result; all three sessions and the editor host exited normally.

Local paths are normalized. The full DOM, binaries, caches, and editor profile are omitted.
