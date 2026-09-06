# Independent C# with netcoredbg release automation

The selected extension ID is `dotnetdev-kr-custom.csharp-with-netcoredbg` and the
display name is `C# (with netcoredbg)`. Settings live in
[`config/variant.json`](../../config/variant.json). The existing extension and
production workflow are independent.

## Entry points

- `release-netcoredbg.yml`: scheduled tag discovery and manual selection.
  Research-branch manual runs cannot publish.
- `netcoredbg-candidate.yml`: reusable source validation, VSIX packaging,
  extracted-adapter tests and publication.
- `validate-netcoredbg.yml`: the eight-target source and DAP gate.

The detailed observations and current blockers are in the
[cross-platform report](../../docs/research/2026-09-06-cross-platform-release.md).
Candidate `0.1.4000` passed the complete native matrix, all eight VSIX builds,
all sixteen extracted-adapter .NET 8/10 combinations and the final publication
dry run. Alpine uses repository-owned hosting compatibility code after its
original hosting path crashed. The original Samsung files remain unchanged.
The installed macOS ARM64 VSIX also passed activation and two launch sessions
inside VS Code 1.135.0. Open VSX upload and interrupted-upload recovery remain
unexecuted.

## Identity and source overlay

`overlay.py` operates on a disposable C# checkout after the complete debugger
gate passes. It verifies archive hashes, changes the small known integration
points and fails if those upstream anchors move. Samsung source is not edited.
`npm run compile` and `test-factory.cjs` passed locally against an actual overlaid
C# source snapshot with synthetic packaging inputs. That was a compile/factory
test. The subsequent real VSIX candidate and local editor-host results are
recorded separately in the report.

Only `coreclr` is advertised. The package README identifies unsupported or
unverified debugger scenarios and preserves upstream component-license terms.
The runtime acquisition/SDK paths retain their upstream behavior where possible.
The user installs a native SDK matching the selected platform package.

## Release and retry behavior

The detector uses all eligible Samsung tags from the baseline and the highest
version C# tag. Successful source/recipe fingerprints prevent repeated shipping.
The version is independent: `versionPrefix` plus `run_number * 1000 + tag_index`.
The numeric range keeps multiple candidates and scheduler runs distinct.

An ordinary candidate rebuilds and retests all eight debugger targets, including
on C#-only updates. Reusing old validated engines is not implemented yet.
Interrupted Open VSX uploads use the saved draft release's version, VSIX bytes
and evidence. `resume.py` restores the draft assets; `publish.py` validates the
complete set again. It refuses a different file behind an existing version.
If GitHub asset preservation itself was interrupted, missing assets need to be
recovered from the original Actions artifacts before this retry can complete.

Publication uses the existing `OPENVSX_ACCESS_TOKEN` secret through `OVSX_PAT`.
No per-extension namespace creation command runs. Only the final publication
step receives this token. The script verifies registry readback hashes for every
target and marks the variant GitHub release complete only afterward.

## Activation and scope

The initial branch push trigger has been removed after successful verification;
manual dispatch remains available. The research branch runs without publishing.
A workflow on the default branch
can accept manual dispatch and scheduled events. A manual run defaults to
`publish=false`; a scheduled default-branch run publishes only after all gates
pass. The branch has not been merged and no new extension has been published.

Package tests check identity, permissions, absence of vsdbg payload filenames,
exact bundled hashes and DAP execution of the extracted adapter. They do not
establish LSP behavior, attach, remote debugging, Hot Reload or all C# Dev Kit
features. Full editor-host launch was separately checked on one macOS ARM64
machine; that local result is not an eight-platform IDE test.
