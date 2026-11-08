# Installed concurrent file builds and same-file retry

This [#18](https://github.com/rkttu/vscode-csharp-autobuild/issues/18) follow-up adds the optional `concurrent-files` control. Three commands for A and three for B enter separate real SDK builds, which are deliberately held together at file-specific nonce barriers before either is released. The five product modules remain unchanged from merged [PR #41](https://github.com/rkttu/vscode-csharp-autobuild/pull/41), commit `ae48926c7ba10d6f7cac21eeefe000cb49bd1461`. No package is published.

Final native control `n02` passes in **26.04 seconds**, with editor exit 0. Independent compiler-error regression `c01` passes in **30.34 seconds**, also with exit 0. Strict Node **228/228** and Python **39/39** checks pass, without failed, skipped or cancelled intended cases. Neither final installed-editor attempt has an unexpected failure or test safety cleanup.

Earlier control `n01` also passed, in **21.53 seconds**. After that pass, a one-line harness failure-safety change made the bounded cleanup drain include an underlying command that can remain pending after a dispatch callback throws. The final control and compiler regression use the corrected driver. The earlier pass retains its original bytes and is listed separately, rather than treated as a failed attempt or current-harness coverage. The positive controls do not exercise that callback-failure branch.

## Concurrent preparation and file ownership

The candidate and pinned runtime dependency are normally installed in a fresh Windows ARM64 VSCodium `1.143.17232` profile (API `1.143.1`), using SDK `10.0.403`. The prepared A and B files use the same Web fixture with LF newlines, distinct `parallel-a`/`parallel-b` revisions and separate barrier nonces, markers and release paths. A pinned test target runs its bounded inline task inside each SDK process before `CoreCompile`. Its actual `Compile` items must include the requested source and exclude the other source.

1. Dispatch three public commands while A is active, then switch to B and dispatch three more without awaiting A's results. Record each group's active/source identity and fresh application token.
2. Wait for both SDK readiness markers. Independently query each captured PID through CIM and match executable, source/output command arguments and creation time against its in-process marker. At the common pre-release checkpoint, both PIDs are alive, both command groups are pending, neither operation has settled and both release paths are absent.
3. In final control `n02`, the independently held SDK PIDs are **A `89320`** and **B `46292`**. Only after that joint checkpoint does the driver write each exact nonce release. The quoted output log contains one real build per source before release and still exactly one per source after completion.
4. The released builds produce two real native debug sessions. Each three-caller group returns `[true, true, true]` and owns one captured session, distinct output/program paths, debuggee PID and HTTP token. Native DAP launch arguments map to the corresponding source/output; the HTTP response serves that file's own revision. DLL/PDB path, positive byte count and SHA-256 are sampled before cleanup. A also exercises its source breakpoint/evaluation.
5. Stop A and observe its exact editor termination, PID release, reusable port and output/queue cleanup while B survives. Make a dirty A revision edit and disable its one-shot barrier. Three retry callers share one saved real build, fresh session/token/output and the new HTTP revision. B keeps its original session, PID, response, output and byte-identical source/profile. Initial barrier markers remain unchanged. Finish three A Stop cycles and B's final Stop.

These are **fixture-induced overlapping builds**. The shared checkpoint proves two independent preparations are in flight under this control; it does not measure unconstrained scheduling, throughput or a product latency budget. B liveness and resource absence are sampled at explicit checkpoints.

## Retained evidence

Raw profiles and logs remain under `validation-artifacts/concurrent-files-2026-11-08/`: final control `n02`, final compiler regression `c01`, unit `tests` and earlier passing `n01`. [summarize.py](summarize.py) validates the exact Git product base, candidate/archive/installed bytes, prepared target and file directives, live SDK-instance proof, quoted log slices, trace-bound dispatch/hold/release records, native mapping, source/profile snapshots and retry/B checkpoints. It distinguishes live initial session snapshots from later terminated snapshots and retains loaded runtime paths and adapter/Stop diagnostics.

[evidence-summary.json](evidence-summary.json) is **222,898 bytes**, SHA-256 `2ceb426d5f251bbfdbd9ccaca29ae50195847cd4d0e084daad894959d832a810`.

| Retained input | SHA-256 |
| --- | --- |
| Final `n02` local candidate ZIP | `e2f84716eae3aa44f457cc145311498c554ee5d05f48cf11a1512d9788611db5` |
| Final `c01` local candidate ZIP | `27112a4956e711babaa7654a08ef7b3957b01665451aaeb046f1d0346b523f5a` |
| Earlier `n01` local candidate ZIP | `d634787da803a433c44ab931607c7f4ebfab1fcd3d17c4f32f76b1c381fcad2a` |
| Shared content build ID | `3a714b88541bd744dbc9a6f65852a5ae343d6029a0567513e62e6fc9518bc98f` |
| Final unit source/attempt manifest | `9adb503e32806ebcfba0d41feb52b3b9a1ac63185c2af169ccb4435345ad7de5` |

The final unit manifest retains all **48** tracked or new unignored `scripts/variant` source byte copies with pre-run hashes, final verification time, exact argv, complete results/logs and verification-runtime hashes. The collector checks the complete source-path set and historical/current bytes. Earlier `n01` retains driver SHA-256 `fcf48fcae81094cf5568495851b89264d0f276144bf0e8a5a816d9c3e1f394e8`; its executed copy must differ from the current driver only by the declared one-line failure-drain change. All other prepared harness hashes must match current source.

Initial A/B source snapshots preserve their exact LF bytes. Dirty retry comparison permits only barrier disablement, revision change and editor CRLF/LF normalization, while snapshot hashes remain exact. Generated artifact bytes are removed by normal owned cleanup; their sampled metadata is retained. Output log slices retain their exact UTF-16 boundaries, prefix/tail hashes and JSON-quoted process arguments.

## Reproduction

Run from the repository root with the pinned inputs and choose a fresh short artifact name. The driver releases both barriers itself after proving they are simultaneously held.

```powershell
$python = 'C:\Users\rkttu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$workspace = 'D:\Projects\vscode-csharp-autobuild'
$artifactRoot = Join-Path $workspace 'validation-artifacts/concurrent-files-2026-11-08'
$base = Join-Path $workspace 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$runtime = Join-Path $workspace 'validation-artifacts/web-lifecycle-2026-11-05/resources/ms-dotnettools.vscode-dotnet-runtime-3.2.0.vsix'
$work = Join-Path $artifactRoot 'n03' # must be new
& $python -B scripts/variant/lifecycle/prepare.py `
  --base-vsix $base --base-sha256 0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5 `
  --runtime-vsix $runtime --runtime-sha256 a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541 `
  --editor 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\VSCodium.exe' `
  --editor-cli 'C:\Users\rkttu\AppData\Local\Programs\VSCodium\bin\codium.cmd' `
  --dotnet 'C:\Program Files\dotnet\dotnet.exe' --sdk-version 10.0.403 `
  --scenario concurrent-files --cycles 3 --work-dir $work
& ./scripts/variant/lifecycle/run.ps1 -WorkDir $work
```

For the separate compiler regression, prepare another fresh directory with the same inputs and `--scenario build-failure-retry --cycles 3`, then use the ordinary launcher. Preserve every attempted profile. Regenerate the retained summary without opening an editor or rerunning suites:

```powershell
& $python -B docs/research/concurrent-files-2026-11-08/summarize.py `
  --run (Join-Path $artifactRoot 'n02') `
  --compiler-regression (Join-Path $artifactRoot 'c01') `
  --tests (Join-Path $artifactRoot 'tests') `
  --earlier-runs (Join-Path $artifactRoot 'n01')
```

This local command-API slice adds no release qualification. Native macOS, physical F5/menu, notification UI, certificate/trust/UI cancellation, arbitrary host loss, descendants and the full repeated qualification matrix remain outside it. Adapter/Stop diagnostics are preserved alongside behavioral assertions; a passing control is not a claim that every log is error-free.
