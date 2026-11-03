# C# file-based app snippets

Release **11.7.18004** adds 21 repository-owned C# snippets alongside the upstream
extension's existing 42 snippets. It is available on
[Open VSX](https://open-vsx.org/extension/dotnetdev-kr-custom/csharp-with-netcoredbg).
The earlier **LOCAL FBA SNIPPETS TEST** package remains a separate prototype.
The [active-file F5 guide](file-based-apps.md) describes debugging and the Web
startup support included in the same release.

## Use the snippets

Open a C# file. For a complete starter in a new file, use **Snippets: Fill File with
Snippet** and select **FBA: Console application** or **FBA: Minimal web application**.
This command can replace the contents of an existing file. For smaller pieces,
use **Insert Snippet** in the Command Palette or choose an `fba-` suggestion from
IntelliSense (`Ctrl+Space`). Prefix-to-Tab expansion follows the user's
`editor.tabCompletion` setting; suggestion visibility follows the editor's snippet
settings. Packaging these snippets does not require changing those settings.

Use Tab and Shift+Tab to move through placeholders. Choices such as SDK names or
nullable modes offer a fixed list. The generic property/package/project/include
snippets contain placeholders that must be replaced for the intended application.

Put shebangs on the first line, other FBA directives before C# code, executable
fragments among the top-level statements, API routes before `app.Run()`, and JSON
context declarations after all top-level statements. Ordinary static snippets are
selected by language and prefix; they do not analyze the file to relocate code.

## Available prefixes

| Prefix | Inserts | Placement or prerequisite |
| --- | --- | --- |
| `fba-console` | Console application starter | New C# file; .NET 10 SDK |
| `fba-web` | Web SDK / Minimal API starter | New C# file; .NET 10 SDK; disables Native AOT publishing |
| `fba-shebang` | `#!/usr/bin/env -S dotnet --` | First line; Unix `env -S` |
| `fba-shebang-simple` | `#!/usr/bin/env dotnet` | First line; fallback for systems without `env -S` |
| `fba-disableaot` | `#:property PublishAot=false` | Before C# code |
| `fba-sdk` | SDK selection | Before C# code; Worker applications may also need Hosting packages |
| `fba-framework` | `TargetFramework` property | Defaults to `net10.0` |
| `fba-nullable` | Nullable mode | `enable`, `disable`, `annotations`, or `warnings` |
| `fba-property` | MSBuild property name/value | Replace both placeholders |
| `fba-envproperty` | Build property from environment with fallback | Uses MSBuild `ValueOrDefault` |
| `fba-package` | NuGet package reference with explicit version | Replace package name and version |
| `fba-project` | Project reference | Replace the relative project path |
| `fba-include` | Additional C# file | SDK **10.0.300+**; included file contains declarations, not top-level statements |
| `fba-paths` | Optional original source file/directory paths | Top-level statements; values may be absent after publish/pack |
| `fba-env` | Runtime environment variable with fallback | Top-level statements |
| `fba-config` | JSON configuration with environment overrides | Web SDK/shared framework, or the corresponding Configuration packages |
| `fba-mapget` | Text GET endpoint | Existing Web app, before `app.Run()` |
| `fba-mapjson` | Timestamp/random JSON GET endpoint | Existing Web app; use generated JSON metadata for Native AOT publishing |
| `fba-jsoncontext` | JSON source generation context | After top-level statements; replace the model type |
| `fba-jsonserialize` | Serialization with generated metadata | Match the value, context, and generated model metadata |
| `fba-periodic` | Async periodic loop with Ctrl+C cancellation | Top-level statements; disposes timer/token source and removes the event handler |

The standalone snippets do not imply that every selected SDK supplies all APIs.
For example, a Worker SDK application using Generic Host generally also references
`Microsoft.Extensions.Hosting`. The configuration fragment uses explicit static
extension calls so it can be inserted among statements without inserting `using`
directives in the middle of a file. It independently creates a configuration root;
`WebApplication.CreateBuilder` already loads its own default configuration.

For Unix direct execution, save with LF line endings and no BOM, and grant
executable permission. The `-S dotnet --` form forwards CLI-style application
arguments; the shorter fallback can let dotnet consume such options. On Windows,
use `dotnet file.cs` or the extension's F5 command.

The property snippet supplies an editable template. SDK-aware MSBuild property
name/value IntelliSense remains a separate feature under investigation.

The JSON endpoint fragment returns an anonymous object. For Native AOT
publishing, replace that object with a named DTO and generate its JSON metadata;
`fba-jsoncontext` and `fba-jsonserialize` provide the corresponding pieces.

## Sources and packaging

The set adapts small patterns from
[dotnetdev-kr/dotnet-fba-examples at e75e356](https://github.com/dotnetdev-kr/dotnet-fba-examples/tree/e75e35665a8d62f9246e51df1e79275c54f010a6):
shell/source paths, Minimal API/JSON responses, configuration, and cancellable
periodic work. Current directive syntax and requirements follow the
[official file-based app documentation](https://learn.microsoft.com/en-us/dotnet/core/sdk/file-based-apps).

The [snippet JSON](../scripts/variant/file-based-apps/snippets/fba-csharp.json),
[source notice](../scripts/variant/file-based-apps/snippets/NOTICE.md), and
[original MIT license](../scripts/variant/file-based-apps/snippets/examples-LICENSE.txt)
are packaged under `.netcoredbg/snippets/`. The overlay appends a second
`contributes.snippets` entry for `csharp`. Existing upstream snippets and their
registration remain intact. VSIX verification compares every owned asset to the
repository bytes, including the source notice and license.

No additional upstream language-server or editor source changes are required.
Large multi-service Aspire examples, GUI applications, preview AI integrations,
and platform-specific native library builds remain in the source example
repository rather than this compact starter set.

## Local verification

The Windows ARM64 local VSIX SHA-256 is
`19de9ef5cb3812b4593b702dab3cc90b64d11bc9e42bba234f4c96269283c8d5`.
Installed-package checks in VS Code 1.144.1 verified both C# snippet registrations,
the unchanged upstream 42-snippet asset, and insertion of every new snippet by
its registered name. The exact expanded code passed six SDK 10.0.402 build-only
compositions: Console, Web, source paths/environment, periodic work,
configuration/endpoints, and generated JSON metadata. MSBuild evaluation also
verified the environment property's default value and explicit environment
override, exercising literal `$` preservation through real snippet insertion.

All 34 variant Python tests and the pristine upstream integration preflight
passed. The packaged runtime and debugger remain identical to the previously
verified local Web prototype. Evidence is retained under
`validation-artifacts/fba-snippets-local-2026-11-03/editor-test/evidence/`.
These tests did not synthesize typed prefixes, Tab navigation or picker UI,
run the applications, install certificates, open a browser, or execute Unix
shebangs. Existing visible manual-test instances were preserved.

The unchanged CI-built `11.7.18004` Windows ARM64 VSIX separately passed the same
21 insertions, six build compositions and two property evaluations, plus 14 Web
debugging/regression checks. All 29 release jobs passed. The
[release record](research/2026-11-03-file-based-web-snippets-release.md) preserves
its actual package hash and the public-registry verification.
