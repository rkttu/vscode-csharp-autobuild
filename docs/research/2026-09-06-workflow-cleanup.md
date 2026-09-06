# Production workflow and temporary branch cleanup

On September 6, 2026, the maintainer requested removal of the temporary research workflows and branches after the first eight-platform release. The maintainer separately authorized deletion of the five diagnostic workflow runs and their attached artifacts. Research documents, archived diagnostic evidence, production release assets, and Copilot workflow history remain intact.

## 1. Retained production workflows

GitHub's workflow API now lists six active workflows:

| Workflow | Role |
| --- | --- |
| `build-and-release.yml` | Existing upstream-preserving C# publication |
| `release-netcoredbg.yml` | Scheduled and manual entry point for the independent extension |
| `netcoredbg-candidate.yml` | Reusable VSIX packaging, testing and publication |
| `validate-netcoredbg.yml` | Reusable native validation across all eight platforms |
| Copilot code review | GitHub-managed review workflow |
| Copilot cloud agent | GitHub-managed agent workflow |

The two reusable netcoredbg helpers are required dependencies of the scheduled release workflow. Neither has its own schedule or manual dispatch. Manual validation uses the release entry point with `publish` disabled. The native gate no longer exposes the retired Alpine-only experimental scope.

The upstream C# workflow, its `.last_built_sha`, the variant release entry point, and the candidate publication workflow are unchanged by this cleanup. The [README](../../README.md) describes the current operation path.

## 2. Removed experiments and run history

The cleanup removed the Windows-only and Alpine diagnostic YAML files. Their last pre-cleanup versions remain available at commit [`62117f1`](https://github.com/rkttu/vscode-csharp-autobuild/tree/62117f140ed351739889b4f783fe59f42e74c13d/.github/workflows). The old action-upgrade experiment already had no workflow file in main; its remaining GitHub registration was disabled before deleting its final run.

The five explicitly authorized run deletions were:

- `31162731786`: TEMP - Validate action upgrades
- `34016701849` and `34017007698`: Validate netcoredbg on Windows
- `34020196056` and `34020443441`: Diagnose Alpine netcoredbg startup

After deletion, none of those three workflow registrations appeared in the workflow list. Existing [Windows evidence](windows-validation-2026-09-06/) and [Alpine crash evidence](cross-platform-2026-09-06/alpine-crash/) remain in the repository. Human-readable research links now point to archived evidence and historical workflow sources instead of the removed Actions pages.

## 3. Removed temporary branches

Both remote temporary branches were removed:

- `research/netcoredbg-windows-validation`, tip `594c8d9812c4a351dd5e2a32c6ecaaccc1b985a6`, already an ancestor of main
- `copilot/configure-debugger-to-netcoredbg`, tip `b6a401e8c128b1dec3733d39fdf77fc0cdb1e219`, belonging to closed [PR #3](https://github.com/rkttu/vscode-csharp-autobuild/pull/3)

The Copilot branch contained an older unmerged implementation. Before deletion, its full Git history was saved and verified in a local bundle. After deletion, GitHub's `refs/pull/3/head` still resolved to its original tip. The branch was not merged into the upstream-preserving distribution.

The local merged research branch and stale remote-tracking references were also removed. Local and remote branch inventories now contain only main.

## 4. Cleanup verification

Actionlint passed for all four retained YAML workflows. All 43 gate, discovery, versioning, and publication tests passed. Executing the native input-matrix generator produced the same eight configured targets, and both local reusable-workflow references resolved successfully. No native rebuild or new extension release was triggered by the cleanup.

The successful [first-release recovery run](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34034255861) remains available and successful. The release workflow and both Copilot workflows remain active. Workflow-source changes alter the recipe fingerprint, so the next ordinary scheduled poll can select a fresh candidate under the existing version policy; the full validation gate still precedes any upload.
