# Terminal output recovery after host restart

This development change recovers a narrow class of file-debug cleanup failures: a run is already known to be terminal, deletion fails, and the remaining output is successfully published to a versioned terminal queue. It does not infer safety from elapsed time, PID death, editor restart or the absence of a session event.

## Ownership and publication

The runtime first attempts its existing bounded deletion. Only its in-memory owned-output set can authorize preservation after failure. [The recovery module](../../scripts/variant/file-based-apps/recovery.cjs) validates the physical source directory, writes a record in a random staging entry, moves the remaining run into the fixed `output` child, and publishes the complete entry with a rename.

```text
file-based-apps/
  <source-hash>/run-<random>/              # live or unmarked: never scanned
  terminal-cleanup-staging-v1/<uuid>/     # incomplete: never recovered automatically
  terminal-cleanup-v1/<uuid>/
    record.json                          # version, kind and matching entryId only
    output/                              # the only recursive deletion target
```

The receipt contains no deletion path. Its strict schema, bounded regular-file read, name/ID agreement, directory and physical-path checks reject malformed data, links/junctions and unexpected siblings. Same-host staging retries retain the original directory's filesystem identity in memory so replacement at that original path is not moved. Unavailable or zero identity fields leave the original untouched instead of guessing. A stale receipt whose ready entry was already removed never falls back to deleting a replacement at its old run path.

The record is outside `output`, so an interrupted or failed output deletion does not consume the recovery evidence. Metadata/empty-directory cleanup can still fail after the payload is gone; unknown remnants are preserved rather than swept. An unsuccessful move or publication is available for same-host retry, but unmarked runs and incomplete staging are intentionally not recovered by a new host.

## Startup and concurrency

After registering the command and event handlers, activation starts one best-effort background pass. It inspects at most 32 ready entries and attempts one valid cleanup without holding activation or a fresh file command pending. Calls in the same host share a pass. There is no complete-drain or fairness guarantee: invalid entries or a repeatedly failing entry can delay later work.

Ready paths are not reused. Two hosts can therefore clean the same terminal entry idempotently. Repeated tests exposed Windows returning `EPERM` while the other host had already removed a marker or empty entry. The module accepts such an error only after checking that the exact path is absent; a remaining or uncertain path still fails conservatively.

## Validation and limits

- All **128 Node tests** pass under `--unhandled-rejections=strict`, with no skips, in three complete consecutive final runs. All **34 Python tests** pass.
- The **44 recovery cases** include malformed/oversized/version-mismatched records, unknown sibling files, path escape, native junction/symlink and external-sentinel preservation, partial removal, staging failures, unavailable identity, source replacement, bounded scans, and concurrent hosts.
- A native two-process test publishes a terminal entry, exits its owner Node process, then recovers it in a fresh Node process while retaining unmarked output. It does not kill a live .NET build or an installed editor.
- Runtime integration checks fresh activation with another host's live output, stale original-path replacement, unresolved cancelled starts, and nonblocking recovery. The Windows concurrency case passed 25 consecutive targeted runs after its fix.
- A local overlay control loads the packaged entry and new dependency with mocked upstream/editor APIs, preserving command registration and the upstream API. This is not an installed VSIX test.

The tests are reproducible with the commands in [the file-debug guide](../file-based-apps.md#implementation-and-validation); the separate-process control is in [test-recovery.cjs](../../scripts/variant/file-based-apps/test-recovery.cjs). No package version or release is assigned. Installed VSCodium/macOS crash/reload qualification, actual process-tree/Web-port cleanup, arbitrary filesystem-operation time limits, power-loss durability and malicious same-user filesystem replacement remain outside this change. Issue #18 stays open.
