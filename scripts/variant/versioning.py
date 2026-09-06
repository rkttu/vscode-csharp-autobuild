"""Map upstream C# versions to ordered numeric VSIX revisions and traceable tags."""
import re

POLICY = "upstream-patch-revision-v1"
STRIDE = 1000
MAX_COMPONENT = 2147483647


def csharp_version(tag):
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-prerelease)?", tag)
    if not match:
        raise ValueError("Unsupported upstream C# tag: " + tag)
    parts = tuple(map(int, match.groups()))
    if any(value > MAX_COMPONENT for value in parts):
        raise ValueError("Upstream version component exceeds the supported range")
    return ".".join(map(str, parts))


def identity(csharp_tag, debugger_tag, debugger_sha, revision):
    upstream = csharp_version(csharp_tag)
    if type(revision) is not int or not 1 <= revision < STRIDE:
        raise ValueError("Packaging revision must be between 1 and 999; no automatic rollover")
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+", debugger_tag) or not re.fullmatch(r"[0-9a-f]{40}", debugger_sha):
        raise ValueError("Invalid debugger tag or commit")
    major, minor, patch = map(int, upstream.split("."))
    packed_patch = patch * STRIDE + revision
    if packed_patch > MAX_COMPONENT:
        raise ValueError("Encoded patch exceeds the supported range")
    return dict(versionPolicy=POLICY, csharpVersion=upstream, revision=revision,
                version=f"{major}.{minor}.{packed_patch}",
                releaseTag=f"csharp-v{upstream}-netcoredbg-v{debugger_tag}-g{debugger_sha[:12]}-r{revision}")


def validate(candidate):
    expected = identity(candidate["csharpTag"], candidate["debuggerTag"], candidate["debuggerSha"], candidate["revision"])
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise ValueError("Candidate version identity mismatch: " + key)
    if not re.fullmatch(r"[0-9a-f]{40}", candidate["csharpSha"]):
        raise ValueError("Invalid C# source commit")
    return expected
