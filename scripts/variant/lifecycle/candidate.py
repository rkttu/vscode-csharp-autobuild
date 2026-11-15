"""Build or validate the exact local-only lifecycle VSIX payload."""
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
import zipfile

from overlay import FILE_APP_MODULES

EXTENSION_ID = "dotnetdev-kr-custom.csharp-with-netcoredbg"
DISPLAY_NAME = "C# (netcoredbg) LOCAL WEB LIFECYCLE TEST"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _sha256(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(label + " must be a SHA-256 digest")
    return value.lower()


def _payload(raw):
    """Read every entry, rejecting both unsafe names and extraction aliases."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries, aliases = {}, set()
            for info in archive.infolist():
                name = info.orig_filename
                path = PurePosixPath(name)
                unsafe_windows = any(
                    part.endswith((".", " ")) or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                    or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]", part.split(".")[0], re.IGNORECASE)
                    for part in path.parts)
                if (not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name
                        or unsafe_windows or name.rstrip("/") != path.as_posix()):
                    raise ValueError("Unsafe ZIP entry: " + repr(name))
                alias = path.as_posix().casefold()
                if name in entries or alias in aliases:
                    raise ValueError("Duplicate ZIP entry or path alias: " + name)
                aliases.add(alias)
                entries[name] = archive.read(info)
            return entries
    except zipfile.BadZipFile as error:
        raise ValueError("Invalid candidate ZIP: " + str(error)) from error


def _expected_payload(base, modules, target, source_commit, expected_sha):
    expected_sha = _sha256(expected_sha, "Base VSIX SHA-256")
    raw = base.read_bytes()
    if digest(raw) != expected_sha:
        raise ValueError("Base VSIX SHA-256 differs from the pinned input")
    original = _payload(raw)
    package = json.loads(original["extension/package.json"])
    if package.get("netcoredbgBuild", {}).get("target") != target:
        raise ValueError("Base VSIX target differs from the selected native target")
    if f"{package.get('publisher')}.{package.get('name')}" != EXTENSION_ID:
        raise ValueError("Unexpected extension ID")
    if package.get("main") != "./.netcoredbg/entry.cjs":
        raise ValueError("Base VSIX must already contain the owned entry wrapper")
    if not isinstance(package.get("version"), str) or not package["version"]:
        raise ValueError("Base VSIX must declare its version")
    owned = {name: (modules / name).read_bytes() for name in FILE_APP_MODULES}
    identity = {"baseVsixSha256": expected_sha, "sourceCommit": source_commit, "target": target,
                "ownedModules": {name: digest(data) for name, data in owned.items()}}
    build_id = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    package["displayName"] = DISPLAY_NAME
    package["netcoredbgBuild"].update(localCandidate=True, lifecycleBuildId=build_id,
                                      lifecycleSourceCommit=source_commit)
    replacements = {f"extension/.netcoredbg/{name}": data for name, data in owned.items()}
    replacements["extension/package.json"] = (json.dumps(package, indent=2) + "\n").encode()
    try:
        manifest = ET.fromstring(original["extension.vsixmanifest"])
    except ET.ParseError as error:
        raise ValueError("Invalid VSIX manifest XML") from error
    display_names = [element for element in manifest.iter()
                     if element.tag.rsplit("}", 1)[-1] == "DisplayName"]
    if not display_names:
        raise ValueError("Base VSIX manifest must declare its DisplayName")
    for element in display_names:
        element.text = DISPLAY_NAME
    replacements["extension.vsixmanifest"] = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
    immutable = {name: digest(data) for name, data in original.items() if name not in replacements}
    metadata = {**identity, "buildId": build_id, "version": package["version"], "localOnly": True,
                "published": False, "unchangedEntries": len(immutable),
                "unchangedPayloadDigest": digest(json.dumps(immutable, sort_keys=True).encode())}
    return raw, original, replacements, metadata


def _validate_payload(raw, expected):
    actual = _payload(raw)
    if actual.keys() != expected.keys():
        raise ValueError("Candidate contains unexpected or missing payload entries")
    for name, data in expected.items():
        if actual[name] != data:
            raise ValueError("Candidate payload differs from expected bytes: " + name)


def build_candidate(base, modules, target, source_commit, output, expected_sha):
    """Replace only owned modules and local-only metadata; verify all other bytes."""
    raw, original, replacements, metadata = _expected_payload(base, modules, target, source_commit, expected_sha)
    expected = {**original, **replacements}
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = dict(replacements)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive, zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as candidate:
        for info in archive.infolist():
            candidate.writestr(copy.copy(info), pending.pop(info.filename, original[info.filename]))
        for name, data in pending.items():
            candidate.writestr(name, data)
    candidate_raw = output.read_bytes()
    _validate_payload(candidate_raw, expected)
    return {**metadata, "sha256": digest(candidate_raw), "path": str(output.resolve())}


def load_candidate_manifest(manifest, expected_manifest_sha, base, modules, target, source_commit, expected_base_sha):
    """Validate pinned manifest, current source identity and all candidate bytes without writing a ZIP."""
    manifest = Path(manifest).resolve(strict=True)
    manifest_raw = manifest.read_bytes()
    manifest_sha = _sha256(expected_manifest_sha, "Candidate manifest SHA-256")
    if digest(manifest_raw) != manifest_sha:
        raise ValueError("Candidate manifest SHA-256 differs from the pinned input")
    document = json.loads(manifest_raw)
    if (not isinstance(document, dict) or set(document) != {"schema", "candidate"}
            or type(document["schema"]) is not int or document["schema"] != 1
            or not isinstance(document["candidate"], dict)):
        raise ValueError("Expected candidate manifest schema 1")
    candidate = document["candidate"]
    source_text = candidate.get("path")
    if not isinstance(source_text, str):
        raise ValueError("Candidate path must be absolute and canonical")
    source = Path(source_text)
    if not source.is_absolute() or str(source.resolve(strict=True)) != source_text:
        raise ValueError("Candidate path must be absolute and canonical; aliases are not allowed")
    candidate_raw = source.read_bytes()
    candidate_sha = _sha256(candidate.get("sha256"), "Candidate SHA-256")
    if digest(candidate_raw) != candidate_sha:
        raise ValueError("Candidate SHA-256 differs from the manifest")
    _, original, replacements, metadata = _expected_payload(base, modules, target, source_commit, expected_base_sha)
    expected_metadata = {**metadata, "sha256": candidate_sha, "path": str(source)}
    for name, value in expected_metadata.items():
        if json.dumps(candidate.get(name), sort_keys=True) != json.dumps(value, sort_keys=True):
            raise ValueError("Candidate metadata differs from current inputs: " + name)
    if candidate.keys() != expected_metadata.keys():
        raise ValueError("Candidate metadata contains unexpected or missing fields")
    _validate_payload(candidate_raw, {**original, **replacements})
    return {"candidate": copy.deepcopy(candidate), "bytes": candidate_raw,
            "reuse": {"manifestPath": str(manifest), "manifestSha256": manifest_sha,
                      "sourcePath": str(source), "sourceSha256": candidate_sha, "method": "byte-copy"}}


def copy_candidate_manifest(validated, output):
    """Exclusively create a profile copy of already validated, frozen bytes."""
    output = Path(output)
    resolved = output.resolve()
    if resolved in (Path(validated["reuse"]["sourcePath"]), Path(validated["reuse"]["manifestPath"])):
        raise ValueError("Candidate copy path aliases its source or manifest")
    raw = validated["bytes"]
    if digest(raw) != validated["candidate"]["sha256"]:
        raise ValueError("Validated candidate bytes changed before copying")
    # Retain an incomplete newly created file if an actual write fails: it is
    # original failure evidence. All validation happens before this exclusive open.
    with output.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("Incomplete candidate byte copy")
    candidate = copy.deepcopy(validated["candidate"])
    candidate["path"] = str(resolved)
    return candidate, copy.deepcopy(validated["reuse"])
