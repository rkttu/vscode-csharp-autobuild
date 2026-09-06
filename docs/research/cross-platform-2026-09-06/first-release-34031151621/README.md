# First-release validation and completed publication

Main run 34031151621 passed eight native builds and eight extracted-VSIX gates on .NET 8/10, including the 30 upstream DAP scenarios per combination. Its first upload attempt stopped after Open VSX acknowledged Windows x64 but before public metadata became available. The draft preserved all 19 tested release assets.

[Recovery run 34034255861](recovery-34034255861/README.md) completed publication of version `2.148.23001` on all eight targets without rebuilding. Both the workflow and an independent download check verified every public VSIX against the original release manifest. The paired GitHub release is public and retains the original validated commit and assets.

The [first-release report](../../2026-09-06-first-release.md) explains the asynchronous-publication wait, discovery permission correction, scheduled operation, and remaining functional boundaries. This archive retains the original failure and partial-publication snapshots alongside the successful recovery. `old-schedule-darwin-arm64.json` records a separate .NET 10 upstream exception-test failure from the old scheduled run; those failed artifacts were not published. No VSIX or debugger binary is committed here.
