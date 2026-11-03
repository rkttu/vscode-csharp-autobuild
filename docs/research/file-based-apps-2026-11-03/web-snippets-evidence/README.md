# Web bootstrap and snippet evidence

The `local-web/` and `local-snippets/` directories preserve two **local prototype** runs assembled over the public `11.7.18003` engine payload. They are not downloaded public `11.7.18004` packages. Their package hashes and results must remain distinct from the CI package reruns below and the separate public-release verification.

Both runs used Windows ARM64, VS Code `1.144.1`, and .NET SDK `10.0.402`, with the target VSIX installed normally in a new isolated hidden profile. The test driver was a separate extension. The provenance records compare the installed files and confirm that the language-service and debugger engine bytes were unchanged from public `11.7.18003`.

## Local Web bootstrap

- Package SHA-256: `6a390dcaf06b6b803b6b76a4d758b40c911a523afbb06daffda998b19786fc8d`.
- **14 checks passed**, covering the registered F5 binding and command, compiler-error notification/retry, source breakpoints and stepping, same-file Web SDK conversion, HTTP launch-profile arguments/environment, selected-project fallback, and session cleanup.
- A real ASP.NET Core process emitted its listening event and answered the owned loopback HTTP request. A recorder configured only in the isolated profile confirmed that `serverReadyAction` invoked the external launcher with the expected URL; it did not render a browser UI or change the OS default browser.
- [Provenance](local-web/provenance.json), [editor results](local-web/editor-result.json), [DAP trace](local-web/editor.dap.jsonl), [launcher observation](local-web/browser-observation.jsonl), and [process cleanup](local-web/process-exit.json) retain the results. The directory also contains the normalized test driver and recorder source.

## Local static snippets

- Package SHA-256: `19de9ef5cb3812b4593b702dab3cc90b64d11bc9e42bba234f4c96269283c8d5`.
- All **21 FBA snippets** expanded through the registered `editor.action.insertSnippet` command, while the **42 upstream C# snippets** remained packaged.
- **Six representative source compositions built successfully**: Console, Web, source paths/environment property, periodic loop, configuration/endpoints, and JSON source generation. **Two MSBuild property evaluations** confirmed environment-variable and fallback values. These applications were not executed or published.
- [Provenance](local-snippets/provenance.json), [editor expansions](local-snippets/editor-result.json), [build/evaluation results](local-snippets/build-result.json), [expanded sources and logs](local-snippets/builds/), and [process cleanup](local-snippets/process-exit.json) preserve the results. The directory also contains the exact snippet snapshot and normalized test/build drivers.

## Actual CI package 11.7.18004

The `ci-web/` and `ci-snippets/` directories preserve separate reruns using the unchanged Windows ARM64 VSIX from [CI run 41644074504](https://github.com/rkttu/vscode-csharp-autobuild/actions/runs/41644074504), source commit `ca5d10d97431181d934369c76c28347fac8a05a6`. The artifact was installed normally in fresh isolated profiles on Windows ARM64 / VS Code `1.144.1` / SDK `10.0.402`; the target extension was not injected as a development extension. Public-registry package byte identity is a separate verification.

- VSIX SHA-256: `0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5`.
- This run's debugger executable SHA-256: `29addd991c76cccc31e0cb58414ed3f5dce533842f63e58443ef4188861ad769`; debugger archive SHA-256: `cfc272be9e883bcb90c9ed0704731fbb1349faf207d872f71e6bfb83b55869ad`. The native debugger was rebuilt at the same upstream version pins, so these records compare all 16 debugger files to **this run's** validation manifest rather than assuming byte identity with `11.7.18003`.
- **14 Web checks passed across four actual debug sessions**, including notification/retry, HTTP profile and endpoint debugging, automatic launcher recording, selected-project fallback, and cleanup. See [provenance](ci-web/provenance.json), [editor results](ci-web/editor-result.json), [DAP trace](ci-web/editor.dap.jsonl), [launcher observation](ci-web/browser-observation.jsonl), and [process cleanup](ci-web/process-exit.json).
- **21 snippet expansions, six representative builds, and two MSBuild property evaluations passed**; the 42 upstream snippets remained packaged. Applications in these build compositions were not executed. See [provenance](ci-snippets/provenance.json), [editor expansions](ci-snippets/editor-result.json), [build/evaluation results](ci-snippets/build-result.json), [sources and logs](ci-snippets/builds/), and [process cleanup](ci-snippets/process-exit.json).
- Both provenance records confirm archive-to-install equality for the four owned modules, three snippet/notice assets, original `dist/extension.js`, and the debugger payload. The 10 Web files and 22 snippet files were copied unchanged from normalized evidence, with a matching SHA-256 checked for every copy. The same private-path and credential-pattern scan found no matches.

## Publication and independent readback

The [29-job summary](publication/run-summary.json) records the successful
`41644074504` workflow. The [publisher status](publication/publisher-publication-status.json)
records all eight verified targets. The independent
[readback summary](publication/readback-summary.json) confirms eight exact-version
records and eight platform-specific latest feeds at `11.7.18004`.

The public Windows ARM64 VSIX has SHA-256
`0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5`,
identical to the installed/tested CI package above. The public release/native
manifests and registry metadata are preserved in `publication/`. Source-owned
module/asset and native payload comparisons passed. No binary package or editor
profile is committed here.

## Scope and normalization

The editor runs did not synthesize physical F5 input. Snippet checks did not type prefixes, exercise Tab completion, or operate the snippet picker UI. No Unix shebang execution, real browser rendering, HTTPS/TLS, or development-certificate trust operation is established by these records. Certificate setup branches are covered only by mocked unit tests in [test-web.cjs](../../../../scripts/variant/file-based-apps/test-web.cjs); those mocks do not establish OS trust behavior. These Windows ARM64 checks do not establish editor UI behavior on the other release platforms or in Cursor.

The 10 Web files and 22 snippet files were copied unchanged from the already normalized local evidence directories, with matching SHA-256 values checked for every copy. Absolute private paths use placeholders such as `<workspace>`, `<dotnet-root>`, `<local-web-editor-root>`, and `<snippet-editor-root>`. A further scan found no private absolute paths, local identity, email addresses, or credential-pattern matches. Binaries, VSIX packages, editor profiles, caches, and raw browser/editor DOM are omitted.
