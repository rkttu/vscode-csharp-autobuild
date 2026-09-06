"""Find unshipped Samsung tags and the latest C# tag without using releases/latest."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def gh_pages(endpoint):
    pages = json.loads(subprocess.check_output(["gh", "api", "--paginate", "--slurp", endpoint], text=True))
    return [item for page in pages for item in page]


def tags(repository):
    lines = subprocess.check_output(["git", "ls-remote", "--tags", "https://github.com/" + repository + ".git"], text=True).splitlines()
    result = {}
    for line in lines:
        sha, ref = line.split()
        name = ref.removeprefix("refs/tags/")
        if not name.endswith("^{}"):
            result[name] = sha
    for line in lines:
        sha, ref = line.split()
        if ref.endswith("^{}"):
            result[ref.removeprefix("refs/tags/")[:-3]] = sha
    return result


def recipe_fingerprint():
    files = [p for directory in ("scripts/validation", "scripts/variant", "config", "assets/netcoredbg")
             for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += list((ROOT / ".github/workflows").glob("*netcoredbg*.yml"))
    digest = hashlib.sha256()
    for file in sorted(files):
        digest.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()


def metadata(body):
    match = re.search(r"<!-- netcoredbg-variant: (\{[^\n]+\}) -->", body or "")
    return json.loads(match[1]) if match else None


def discover():
    config = json.loads((ROOT / "config/netcoredbg.json").read_text())
    variant = json.loads((ROOT / "config/variant.json").read_text())
    samsung = tags("Samsung/netcoredbg")
    csharp = tags("dotnet/vscode-csharp")
    version_key = lambda name: tuple(map(int, re.findall(r"\d+", name)))
    assert samsung[config["baselineTag"]] == config["baselineCommit"], "Baseline tag was moved upstream"
    csharp_tag = os.environ.get("INPUT_CSHARP_TAG") or max(
        (tag for tag in csharp if re.fullmatch(r"v\d+\.\d+\.\d+(?:-prerelease)?", tag)), key=version_key)
    assert csharp_tag in csharp
    selected_tag = os.environ.get("INPUT_DEBUGGER_TAG")
    eligible = [selected_tag] if selected_tag else [tag for tag in samsung
                 if re.fullmatch(r"\d+\.\d+\.\d+-\d+", tag) and version_key(tag) >= version_key(config["baselineTag"])]
    assert all(tag in samsung and re.fullmatch(r"\d+\.\d+\.\d+-\d+", tag) for tag in eligible)
    releases = gh_pages("repos/" + variant["repository"] + "/releases?per_page=100")
    shipped_metadata = [data for release in releases if not release["draft"]
                        and (data := metadata(release["body"])) and data.get("published") is True]
    shipped = {data["fingerprint"] for data in shipped_metadata}
    resumable = {data["fingerprint"]: dict({key: value for key, value in data.items() if key != "published"}, resumeRelease=release["tag_name"])
                 for release in releases if release["draft"] and (data := metadata(release["body"]))
                 and data.get("published") is False}
    shipped_debuggers = {data["debuggerSha"] for data in shipped_metadata}
    latest_validated = max(shipped_metadata, key=lambda data: version_key(data["debuggerTag"]), default=None)
    if not selected_tag:
        eligible = [tag for tag in eligible if samsung[tag] not in shipped_debuggers
                    or (latest_validated and tag == latest_validated["debuggerTag"])]
    recipe = recipe_fingerprint()
    candidates = []
    if not selected_tag:
        # Complete an interrupted multi-platform upload from its preserved bytes.
        candidates.extend(resumable.values())
    for index, tag in enumerate(sorted(eligible, key=version_key, reverse=True)):
        fingerprint = hashlib.sha256((samsung[tag] + csharp[csharp_tag] + recipe).encode()).hexdigest()
        if fingerprint in shipped:
            continue
        if fingerprint in resumable:
            if selected_tag:
                candidates.append(resumable[fingerprint])
            continue
        # Each scheduling run reserves a disjoint numeric range, including dry runs.
        patch = int(os.environ.get("GITHUB_RUN_NUMBER", "1")) * 1000 + index
        candidates.append(dict(debuggerTag=tag, debuggerSha=samsung[tag], csharpTag=csharp_tag,
                               csharpSha=csharp[csharp_tag], recipe=recipe, fingerprint=fingerprint,
                               artifactPrefix=fingerprint[:16], version=variant["versionPrefix"] + "." + str(patch)))
    # Keep matrices within GitHub limits; remaining tags are reconsidered next poll.
    result = dict(include=candidates[:16])
    Path("candidate-matrix.json").write_text(json.dumps(result, indent=2) + "\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        out.write("matrix=" + json.dumps(result, separators=(",", ":")) + "\n")
        out.write("has-candidates=" + str(bool(candidates)).lower() + "\n")
    print(json.dumps(dict(selected=len(result["include"]), backlog=max(0, len(candidates) - 16), candidates=result), indent=2))


if __name__ == "__main__":
    discover()
