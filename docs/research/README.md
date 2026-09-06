# Samsung debugger research

These reports record the investigation completed on September 6, 2026. They distinguish observed builds and DAP results from proposed extension integration and publication behavior. Follow-up work is tracked in [issue #2](https://github.com/rkttu/vscode-csharp-autobuild/issues/2).

1. [Open-source debugger integration](2026-09-06-debugger-integration.md): release assets, local DAP checks, integration points, and alternative engines.
2. [Source-preserving netcoredbg builds](2026-09-06-netcoredbg-source-build.md): macOS source-build results, eight-target feasibility, dependencies, and validation limits.
3. [Libre C# product assessment](2026-09-06-libre-csharp-product.md): preserving the existing distribution, support criteria, and comparison with the community extension.
4. [Separate Samsung debugger variant](2026-09-06-samsung-debugger-variant.md): the proposed `C# (with Samsung Debugger)` identity and independent build and publication paths.

The adjacent dated evidence directories contain source hashes, API snapshots, build logs, and DAP traces. Personal paths in archived evidence were replaced. The original DAP fixture and probe are preserved with their macOS ARM64 experiment; those historical results do not establish execution on other platforms.

The existing production workflow and `dotnetdev-kr-custom.csharp` publication policy remain unchanged.
