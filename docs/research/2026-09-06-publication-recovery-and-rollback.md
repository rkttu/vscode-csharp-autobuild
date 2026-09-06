# Publication recovery and rollback boundaries

On September 6, 2026, the independent netcoredbg variant had completed its eight-platform publication dry run but had not uploaded to Open VSX. This follow-up reviewed interruption recovery and post-publication rollback against the current repository code and the public registry. A read-only request to `https://open-vsx.org/api/version` returned `{"maxExtensionSize":262144000,"version":"v1.1.2"}`. [Successful candidate](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34023125844), [public version endpoint](https://open-vsx.org/api/version)

The review covers partial uploads, withdrawal of a defective version, recovery for installed users, gaps in the current automation and the effect on operational readiness. It does not execute publication, deletion or rollback.

The sections distinguish completing an interrupted release from replacing a defective release, then identify the changes that would support an automated recovery procedure.

## 1. Interrupted publication of an otherwise valid candidate

The publisher uploads eight platform packages sequentially. Before the first Open VSX upload, it preserves the exact tested VSIX files, debugger archives, manifests and evidence in a draft GitHub release. A network error after three successful uploads can therefore leave three platforms publicly available while five are missing. The draft GitHub release does not hide packages already accepted by Open VSX. There is no all-platform atomic publication in this implementation. [Publisher](../../scripts/variant/publish.py)

The next discovery run selects incomplete drafts for recovery. `resume.py` restores the original files and candidate identity. The publication gate checks the preserved VSIX hashes against their runtime evidence. For each platform, the publisher downloads an existing registry package and compares its hash, or uploads it if the metadata endpoint returns 404. Only after all eight readbacks match does it mark the GitHub release complete. [Discovery](../../scripts/variant/discover.py), [resume helper](../../scripts/variant/resume.py)

If all eight registry uploads succeed but the final GitHub update fails, recovery can verify the existing eight files and finish that update without uploading replacements. If the initial GitHub asset upload was interrupted, recovery can stop on missing original assets. A token failure, hash disagreement, deleted reserved version or repeatable registry rejection also stops recovery; these conditions are not repaired by simply repeating the upload.

This path resumes an intended release. It does not restore an earlier debugger, remove a defective release, or repair a user's local installation. Live interrupted-publication recovery remains unexecuted.

## 2. Registry withdrawal of a defective version

The public Open VSX operating guide documents self-service deletion through the profile menu, Settings, Extensions, and the deletion control for published versions. A publisher can select particular versions instead of deleting the extension. When an aliased version is removed, the registry reassigns `latest` or `preview` to the highest remaining version in the corresponding channel. [Public registry management guide](https://github.com/EclipseFdn/open-vsx.org/wiki/Managing-Extensions#deleting-selected-versions)

The v1.1.2 server implementation removes version files while retaining the version identity. Normal deletion therefore does not make the same namespace/name/platform/version available for different bytes. Administrative purge is a separate privileged operation and is not a publisher rollback mechanism. The eight platform variants should be treated as one incident release while explicitly recording which targets have been withdrawn. [v1.1.2 deletion implementation](https://github.com/eclipse-openvsx/openvsx/blob/v1.1.2/server/src/main/java/org/eclipse/openvsx/ExtensionService.java)

The current development CLI documentation describes `ovsx unpublish`, including version and target filters, but requires registry 1.2.0 or later. The public server reported v1.1.2 during this review, and this repository pins the publishing CLI to 1.1.1. The new CLI command is therefore not presented here as an executable recovery command for the present setup. The documented web management path remains the applicable withdrawal procedure. [Development CLI documentation](https://github.com/eclipse-openvsx/openvsx/blob/main/cli/README.md#delete-extensions), [current workflow](../../.github/workflows/netcoredbg-candidate.yml)

## 3. Installed users and a higher recovery version

Registry withdrawal removes a distribution source; it does not replace the files already installed on user machines. A user can install a retained older version or a preserved VSIX and control automatic updates. Exact interaction details depend on the editor. The VS Code documentation describes Install Another Version, VSIX installation and per-extension auto-update controls; this review did not execute a VSCodium downgrade. [VS Code extension management](https://code.visualstudio.com/docs/configure/extensions/extension-marketplace)

For normal update delivery, a recovery package can restore the known-good debugger under a higher package revision. For example, if `2.148.23001` contains working engine A and `2.148.23002` contains defective engine B, `2.148.23003` can contain engine A again. The package still records the actual engine A tag and full commit. Its changed version metadata creates new VSIX bytes, so all targets pass validation again before publication. Users with automatic updates enabled can then receive the correction as a newer release. This is a proposed operating procedure, not an implemented rollback workflow. [Version policy](2026-09-06-versioning-and-merge-readiness.md)

The same example assumes the C# source base remains `2.148.23`. Restoring the C# source itself from `2.148.24` to `2.148.23` produces a lower numeric version under the current formula, even with a larger packaging revision. That case needs an explicit version-policy decision separating release ordering from the actual source version, or a forward fix on the newer C# base. Provenance should continue to state the source actually used.

## 4. Gaps found in the current release automation

The following findings come from code inspection and a small offline discovery simulation. They do not invalidate the successful native and VSIX tests; they expand the operational scope beyond those tests. [Discovery implementation](../../scripts/variant/discover.py), [release scheduler](../../.github/workflows/release-netcoredbg.yml)

| Condition | Current behavior | Recovery implication |
| --- | --- | --- |
| A draft represents a defective candidate | Discovery selects incomplete drafts for resumption | Cancelling one Actions run does not quarantine the candidate |
| An operator selects an already published, known-good source/recipe combination | Discovery skips its shipped fingerprint | Manual old-tag selection alone does not force a new recovery revision |
| A published debugger is later found defective | Selection still considers its published metadata | Later C# or recipe updates can reconsider that debugger without an explicit exclusion |
| An operator deletes the draft or release history | The allocator loses a revision reservation | Registry version identity can remain reserved despite lost local release metadata |
| C# itself needs restoration to an earlier numeric version | The encoded VSIX version decreases | Automatic update delivery needs an explicit policy for this case |

The offline simulation used two synthetic release records with the same recipe and C# base. It confirmed that the incomplete second release was selected with its original `2.148.23002` version. It also confirmed that explicitly selecting the previously published first debugger produced zero candidates once both release records were marked published. The simulation used temporary files and mocked tag/release reads; it performed no GitHub or registry mutation.

## 5. Proposed incident controls and verification

An operating procedure can first pause the separate variant workflow and stop active publication, then classify the failure as transient interruption or a defective candidate. Transient interruption can resume from the preserved draft. A defective candidate can instead be marked withdrawn or blocked, with its version reservation retained. The original unmodified C# workflow remains independent. [Workflow separation](../../.github/workflows/release-netcoredbg.yml)

The proposed implementation additions are:

- A publication pause control checked by discovery and the final publisher, plus an active-run cancellation procedure
- Explicit blocked or withdrawn candidate/source records that override automatic draft resumption and tag selection
- A recovery-release entry point selecting a known-good source pair or preserved release and allocating a higher revision even when that source fingerprint has shipped before
- Provenance fields connecting the recovery release, defective release and original known-good release
- Offline interruption tests for partial upload, finalization-only retry, hash mismatch, missing assets and withdrawal, followed by an isolated-registry end-to-end exercise

Automatic deletion on a failed upload would not be the default behavior. A client timeout can occur after the server accepted a package, and removing successful uploads does not retract copies users already installed. The preserved release and registry readback supply the evidence needed to decide whether to resume or withdraw. [Current readback checks](../../scripts/variant/publish.py)

## 6. Revised operating-readiness assessment

The earlier merge review established branch compatibility, source/build isolation and successful all-target validation. This follow-up identifies missing controls for deliberate withdrawal and recovery releases. Completing these controls and testing interruption recovery would support enabling unattended public publication. [Earlier merge assessment](2026-09-06-versioning-and-merge-readiness.md)

The available registry deletion path can stop further downloads of a bad version. A higher recovery version can deliver the known-good debugger to installed users through normal updates. The current repository implements partial-publication resumption, while deliberate rollback and quarantine remain proposed work. No extension was published or deleted during this review.

## 7. Maintainer-led operation after failed validation

The maintainer subsequently selected a simpler operating direction: keep tracking releases, treat a detected build or functional problem as a failed Actions run, and respond to GitHub's failure notification. Under this direction, automatic rollback, a quarantine state machine and a separate notification service are not prerequisites for initial operation. The immediate implementation priority is broader functional validation with strict failure propagation. The thirty upstream DAP scenarios discussed in the follow-up are not yet integrated into the release gate. The current eight-check probe remains the executed functional coverage. [Current probe](../../scripts/validation/dap_probe.py), [upstream default test list](https://github.com/Samsung/netcoredbg/blob/9744e1f051866215611b8440c638042aa2aa2f72/test-suite/run_tests.sh)

The existing workflow already propagates native and VSIX validation failures instead of treating them as successful skips. A failed candidate cannot reach publication. It remains eligible for another scheduled attempt because only published fingerprints are excluded. An offline discovery check confirmed that a failed candidate with no publication record receives the same candidate identity on retry, and that adding a newer tag still selects that newer candidate. Unchanged failures can consequently recur at the six-hour polling interval. No permanent failed-tag database is required for this operating model. [Scheduler](../../.github/workflows/release-netcoredbg.yml), [candidate gates](../../.github/workflows/netcoredbg-candidate.yml), [discovery](../../scripts/variant/discover.py)

The unit of release eligibility is a C# source, debugger source and recipe combination. The scheduler can process several candidates in one run: one candidate can fail while a different fully validated candidate publishes. Also, a registry upload failure can occur after some targets were accepted. A failed workflow therefore does not prove that no package was published. Its summary and artifacts can distinguish pre-publication validation failure from upload interruption; existing preserved-byte recovery remains useful for the latter.

GitHub supports email/web Actions notifications and a failed-workflows-only preference. Scheduled-workflow notifications follow the workflow creator, a later cron editor, or the user who re-enables the schedule as described by GitHub. Repository ownership alone does not establish receipt. The maintainer's personal notification settings and actual email delivery were not inspected or changed during this review. [Notification behavior](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs), [notification settings](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)

GitHub schedules can be delayed or dropped under load, and public-repository schedules are disabled after sixty days without repository activity. A workflow that never starts does not produce a failed run. Periodic confirmation that the schedule remains active covers this separate operating condition without adding release-version state. [Schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

This operating choice keeps the existing numeric version policy and all-target publication requirement. Broader tests reduce the chance of shipping a regression; they do not diagnose every possible installed-user failure. A defect reported after publication can still be handled by the maintainer through stopping further publication and issuing an ordinary corrected release. Automatic recovery-version generation remains deferred.
