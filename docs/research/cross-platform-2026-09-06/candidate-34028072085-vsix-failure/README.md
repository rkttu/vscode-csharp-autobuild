# Blocked extracted-VSIX exception test

Run 34028072085 attempt 2 passed seven extracted-VSIX targets. On macOS ARM64, .NET 8 passed the repository fixture and 29 of 30 upstream scenarios. `VSCodeTestUnhandledException` returned four runtime/synthetic-entry frames without source information. Its original source-frame assertion then threw `NullReferenceException`; the job failed and .NET 10 did not run. Publication was skipped.

The same VSIX debugger passed the unchanged scenario in ten local macOS ARM64 repetitions using .NET 8.0.24. Samsung already attempts exception-stack reconstruction three times when the physical top frame lacks a source line. The available CI transcript does not identify why reconstruction failed. The failure is retained separately from subsequent diagnostic reruns and is not classified as fixed.

The archive normalizes local paths and removes NUL transcript terminators. Provenance records the original and archived hashes.
