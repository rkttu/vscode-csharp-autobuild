# Successful first-release recovery

[Run 34034255861](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/34034255861) completed successfully on September 6, 2026, using main commit `dd115e3`. Discovery selected the preserved revision-1 candidate without source-tag inputs. Build, package, and extracted-VSIX jobs were skipped; the publisher restored the original tested release assets.

The publisher verified the existing Windows x64 download, submitted the other seven targets once each, waited for asynchronous registry visibility, and verified all eight public VSIX hashes. GitHub release 383573361 became public at 12:57:19 UTC with all 19 assets. Its target commit remains the original validated merge commit `dd526c7`.

- `candidate-matrix.json`: exact resumed identity and original recipe fingerprint
- `release-manifest.json`: byte-for-byte equivalent JSON to the original tested release manifest
- `publication-status.json`: successful final state, seven submitted targets, and eight verified targets
- `workflow-result.json`: success and skipped build/test job states
- `publication-excerpt.log`: selected timestamped publisher output with ANSI escapes and the CLI decoration removed
- `github-release.json`: public release identity, paired tag, original commit, metadata and 19 asset records
- `public-state.json`: independent public API and full-download SHA-256 checks for all eight platforms
- `next-automatic-candidate.json`: read-only discovery after publication, selecting revision 2 for the changed recipe rather than reusing revision 1

The next-candidate check did not build or publish revision 2. Publisher and workflow corrections changed the recipe, so the next ordinary poll may build a new candidate even when both upstream tags are unchanged. Future source changes can alter that selection. Every fresh candidate still requires all native and extracted-VSIX gates.
