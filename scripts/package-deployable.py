"""Package an allowlisted source snapshot; never include credentials or lab state."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / ".approval-lab" / "releases"
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = output / f"openshell-keyper-lab-deployable-{stamp}.zip"
    files = [root / name for name in ("README.md", "README.zh-TW.md", "pyproject.toml", "uv.lock", ".gitignore")]
    for directory in ("src", "tests", "docs", "examples", "scripts"):
        for source in (root / directory).rglob("*"):
            if (source.is_file() and not source.is_symlink()
                    and "__pycache__" not in source.parts
                    and (source.suffix in {".py", ".md", ".json", ".xml", ".proto", ".ps1", ".sh"}
                         or source.name == "LICENSE")):
                files.append(source)
    contents = {}
    for source in sorted(files):
        resolved = source.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Source escapes project root")
        contents[source.relative_to(root).as_posix()] = source.read_bytes()
    report_path = root / "docs/evidence/openshell-v0.1.6-live.json"
    receipt_path = root / "docs/evidence/validation-environment.json"
    live_verified = False
    if report_path.is_file() and receipt_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected = receipt.get("validated_source_sha256", {})
        source_matches = bool(expected) and all(
            name in contents and hashlib.sha256(contents[name]).hexdigest() == digest
            for name, digest in expected.items()
        )
        live_verified = bool(report.get("success") and report.get("real_gateway") and source_matches)
    metadata = {
        "format": "openshell-keyper-lab-source-snapshot-v1",
        "created_utc": stamp,
        "source": "working-tree snapshot, including uncommitted changes",
        "openshell_api_commit": "4d4c15c133d40a50234ce9d2d198e5ba79b9553e",
        "live_openshell_verified": live_verified,
        "validation_evidence": "docs/evidence/openshell-v0.1.6-live.json" if live_verified else None,
        "real_keyper_verified": False,
        "offline_dependencies_included": False,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
    }
    contents["DEPLOYMENT-MANIFEST.json"] = (json.dumps(metadata, indent=2) + "\n").encode()
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in contents.items():
            entry = zipfile.ZipInfo("openshell-keyper-lab/" + name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            bundle.writestr(entry, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(archive.relative_to(root))
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
