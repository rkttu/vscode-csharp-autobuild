"""Bind local shutdown implementation bytes; static audit, not Reload evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def source(file):
    data = file.read_bytes()
    return {"path": str(file.resolve()), "bytes": len(data), "sha256": digest(data)}, data.decode("utf-8-sig")


def excerpt(text, start, end):
    first = text.index(start)
    try:
        last = text.index(end, first + len(start))
    except ValueError:
        last = text.index(end.replace("\n", "\r\n"), first + len(start))
    value = text[first:last]
    return {"characterOffset": first, "line": text.count("\n", 0, first) + 1,
            "sha256Utf8": digest(value.encode()), "text": value}


def collect(editor, installed):
    app = editor / "resources/app"
    package = read_json(app / "package.json")
    product = read_json(app / "product.json")
    host, host_text = source(app / "out/vs/workbench/api/node/extensionHostProcess.js")
    desktop, desktop_text = source(app / "out/vs/workbench/workbench.desktop.main.js")
    metadata = read_json(installed / "package.json")
    upstream_path = installed / metadata["netcoredbgBuild"]["upstreamMain"]
    if not upstream_path.is_file():
        upstream_path = upstream_path.with_suffix(".js")
    upstream, upstream_text = source(upstream_path)
    entry, entry_text = source(installed / ".netcoredbg/entry.cjs")
    runtime, runtime_text = source(installed / ".netcoredbg/runtime.cjs")
    host["excerpts"] = {
        "deactivateThenSynchronousSubscriptions": excerpt(host_text, "_deactivate(e){", "async _activateExtension("),
        "allExtensionPromisesAndFiveSecondExitRace": excerpt(host_text, "async _deactivateAll(){", "isActivated(e){"),
        "subscriptionsDisposedByActivatedExtensionDisposable": excerpt(host_text, "static _callActivate(e,", "static _callActivateOptional("),
    }
    desktop["excerpts"] = {
        "testRunnerExit": excerpt(desktop_text, "async _onExtensionHostExit(e){", "async _handleNoResolverFound("),
        "testRunnerCompletion": excerpt(desktop_text, "{if(!this._environmentService.isExtensionDevelopment||!this._environmentService.extensionTestsLocationURI)return;", "findTestExtensionHost(e){"),
    }
    marker = "UC(I9t,{activate:()=>O9t});module.exports=zC(I9t);"
    if upstream_text.count(marker) != 1 or "deactivate" in upstream_text:
        raise ValueError("Review the pinned upstream export audit for these different bytes")
    upstream["exportTable"] = {"characterOffset": upstream_text.index(marker), "text": marker}
    upstream["deactivateLiteralOccurrences"] = 0
    entry["text"] = entry_text
    runtime["excerpts"] = {
        "drainOwnership": excerpt(runtime_text, "    function releaseDisposedResources() {", "    const recovery ="),
        "synchronousDisposalAndReturnedApi": excerpt(runtime_text, "    context.subscriptions.push({", "\n}\n\nmodule.exports"),
    }
    return {"schema": 1, "kind": "local-primary-source-static-audit",
            "scope": "Static callback ordering and pinned local implementation; actual Reload observations are separate",
            "editor": {"version": package["version"], "commit": product["commit"],
                       "applicationName": product["applicationName"]},
            "extension": {"id": metadata["publisher"] + "." + metadata["name"], "version": metadata["version"]},
            "sources": {"extensionHost": host, "desktopWorkbench": desktop, "upstream": upstream,
                        "entry": entry, "runtime": runtime},
            "findings": [
                "The host calls module.deactivate, synchronously disposes subscriptions, and returns only the module Promise.",
                "Host termination races all module deactivation Promises against five seconds.",
                "The pinned upstream CommonJS export table exposes activate but no deactivate.",
                "The repository entry discards the runtime API; runtime disposal starts asynchronous work without returning its completion.",
                "Test runner completion has a nativeHostService.exit path in CLI extension-test mode.",
            ],
            "limits": ["Static source does not establish actual Reload event order or a resource leak.",
                       "The test completion path alone does not establish why an interrupted test RPC returned code zero.",
                       "The host-wide five-second cap is not a guaranteed per-extension drain budget."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor-root", type=Path, required=True)
    parser.add_argument("--installed-extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = collect(args.editor_root.resolve(), args.installed_extension.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size,
                      "sha256": digest(args.output.read_bytes())}))


if __name__ == "__main__":
    main()
