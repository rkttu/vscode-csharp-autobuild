# Extension recommendation controls for the C# variant

Research date: November 3, 2026. Inspected distribution: `dotnetdev-kr-custom.csharp-with-netcoredbg` **11.7.18003**. Client inspection: VS Code **1.144.1**, commit `261c84cb1eddf11235f9e2c921425e9663fbe556`. [Inspection evidence](extension-recommendations-2026-11-03/evidence.json) preserves selected package and host metadata.

## Finding

A VSIX can contribute a default that suppresses all extension recommendation notifications. It has no supported manifest field that selectively removes other extension IDs from the host's recommendations. Targeted exclusion is a user/profile or workspace facility. Registry choice and host recommendation policy are separate.

## What the current package contains

The public VSIX has no extension pack, recommendation fields, or walkthroughs. Its only extension dependency is `ms-dotnettools.vscode-dotnet-runtime`, the .NET Install Tool. It does not declare the Microsoft C# or C# Dev Kit extensions as installation dependencies. Relevant source inspection found no direct missing-extension install recommendation in the owned wrapper or upstream activation/debug code; this is not a claim that every language-server binary notification has been exhaustively excluded.

The packaged README does retain the upstream Dev Kit installation recommendation. It also inherits wording that installing Dev Kit installs this extension, which refers to the upstream Microsoft extension and is misleading under the custom identity. The packaging overlay currently appends the upstream README. Correcting or replacing that section is a package-documentation change; it does not disable the host's recommendation engine. See the [upstream README](https://github.com/dotnet/vscode-csharp/blob/1c27e135b5dada55a240e4a504bafa759ec578e8/README.md#L4) and [overlay](../../scripts/variant/overlay.py).

The inspected VS Code product configuration separately recommends `ms-dotnettools.csdevkit` for C# files, C# language mode, solution/project files, and related configuration files. The actual file-based recommendation engine reads host product data and compares installed extension IDs, rather than treating every C# language provider as the official C# extension. A different publisher/name is not an alias for `ms-dotnettools.csharp`. The exact two UI cards in the user's report were not separately traced. See the [host rule reader and installed-ID checks](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/contrib/extensions/browser/fileBasedRecommendations.ts).

## Supported package-level default

Merge the following into the package's existing `contributes.configurationDefaults`:

```json
{
  "contributes": {
    "configurationDefaults": {
      "extensions.ignoreRecommendations": true
    }
  }
}
```

This is allowed by the inspected host source. The [setting](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/contrib/extensions/browser/extensions.contribution.ts#L197) has no explicit scope override or default-contribution prohibition; the [registry defaults to WINDOW scope](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/platform/configuration/common/configurationRegistry.ts#L846), and the [configuration-default contribution accepts WINDOW](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/api/common/configurationExtensionPoint.ts#L217). A general prohibition on application/machine setting defaults therefore does not prohibit this particular setting.

Its scope is broad: it suppresses extension recommendation notifications for all extensions, retains the Recommended list/manual recommendation query, and does not block installation or dependency/pack installation. Explicit user/workspace values take precedence over contributed defaults. It also does not suppress arbitrary notifications sent by another extension. The [official documentation](https://code.visualstudio.com/docs/configure/extensions/extension-marketplace#_can-i-stop-vs-code-from-providing-extension-recommendations) distinguishes notification suppression from hiding the Recommended view.

Putting this setting under `[csharp]` does not make it C#-specific: it is not a language-overridable setting, and the recommendation notification service reads `extensions` without a language override. This is a source-verified option; no package default was changed or enabled in the user's running profile during this investigation.

## Selective exclusion boundary

Workspace and profile recommendation exclusions are separate host capabilities, not package declarations. They affect recommendation lists and notifications rather than installation permission. An `unwantedRecommendations` property in the extension's own package manifest, or an `extensions.json` merely shipped inside its VSIX, does not configure the user's workspaces. No exclusion instructions are being added to the package documentation.

VS Code combines [profile ignored IDs and workspace unwanted recommendations](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/services/extensionRecommendations/common/extensionIgnoredRecommendationsService.ts). The [recommendation service](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/contrib/extensions/browser/extensionRecommendationsService.ts) and [notification service](https://github.com/microsoft/vscode/blob/261c84cb1eddf11235f9e2c921425e9663fbe556/src/vs/workbench/contrib/extensions/browser/extensionRecommendationNotificationService.ts) filter against that combined list. `extensions.ignoredRecommendations` is not a supported setting for this purpose; the per-profile ignore list uses internal storage.

## Open VSX and other clients

Open VSX supplies the registry/gallery API. [Switching the gallery](https://github.com/eclipse-openvsx/openvsx/wiki/Using-Open-VSX-in-VS-Code) does not replace all host recommendation rules. VS Code-derived clients can retain, remove, or replace those rules, and other clients such as Theia have their own recommendation implementation. Therefore Open VSX use alone does not prove either that Microsoft recommendations will appear or that they will be absent.

The same VSIX default can affect clients that support the same setting and contribution semantics; each client's behavior must be checked. A host maintainer could add this variant's ID to a recommendation's `whenNotInstalled` condition. That is a host configuration change, not a VSIX declaration. The inspected [manifest contract](https://code.visualstudio.com/api/references/extension-manifest) and [VSIX metadata writer](https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts) provide no general alternative-provider/extension-ID alias contract. `extensionKind` selects execution location and is unrelated to recommendation suppression.

## Maintainer decision

Remove only the inherited Dev Kit recommended-install section and the introduction's claim that this custom extension ships with Dev Kit. Do not add broad recommendation-suppression defaults or instructions to disable or ignore other extensions. The packaging overlay now filters only that README material, with a checked upstream section boundary; runtime and recommendation settings are unchanged.

The inspected `11.7.18003` package remains the historical baseline for this report. The README change applies to subsequent packaging. The research document and its evidence alone are outside the release recipe; the README-generation overlay change is part of the packaging recipe.
