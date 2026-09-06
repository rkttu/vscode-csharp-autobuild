# Final candidate validation before main adoption

[Run 34028072085](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34028072085) completed successfully on attempt 3 at workflow commit `b919f8e16f492a5dd1d560c750d90ddc3111003c`. It did not publish. The native Intel macOS startup failure and ARM64 macOS extracted-VSIX exception-stack failure remain in separate sibling archives. Neither was removed from the gate.

The final set contains eight native targets, two runtimes per target, eight repository fixture checks and 30 upstream scenarios per runtime, repeated against every extracted-VSIX debugger. The summary validates exact upstream scenario order and debugger hash equality against the native results. Each target preserved all 498 original Samsung files. The final publication preflight accepted all eight VSIX hashes.

Root README/research-only commits after the tested workflow commit do not change recipe `ee1443d0d2bc0a76dfbd129e574126d6badfeaa9a55bf7aed861750df4f085f5`. A separate main-branch run performs the actual release.
