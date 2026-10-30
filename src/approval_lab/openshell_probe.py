"""Read-only environment/source probe; does not apply OpenShell policies."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request


SOURCE_COMMIT = "4d4c15c133d40a50234ce9d2d198e5ba79b9553e"
SOURCE_PATHS = (
    "proto/openshell.proto",
    "proto/gateway_interceptor.proto",
    "proto/sandbox.proto",
    "crates/openshell-gateway-interceptors/src/routes.rs",
)


def check_command(name, args):
    executable = shutil.which(name)
    if executable is None:
        return {"available": False, "reason": "not_on_path"}
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # WSL emits UTF-16LE on Windows, other tools generally emit UTF-8.
        raw = result.stdout + result.stderr
        encoding = "utf-16-le" if b"\x00" in raw else "utf-8"
        return {"available": result.returncode == 0, "exit_code": result.returncode,
                "output": raw.decode(encoding, errors="replace").strip()[:2000]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": type(exc).__name__}


def inspect_sources(sources):
    """Source-shape checks, deliberately not a protobuf or runtime validator."""
    api = sources["proto/openshell.proto"]
    interceptor = sources["proto/gateway_interceptor.proto"]
    routes = sources["crates/openshell-gateway-interceptors/src/routes.rs"]
    route_match = re.search(r"INTERCEPTABLE_METHODS[^=]*=\s*&\[(.*?)\];", routes, re.S)
    request_match = re.search(r"message UpdateConfigRequest\s*\{(.*?)\n\}", api, re.S)
    request = request_match.group(1) if request_match else ""
    return {
        "update_config_allowlisted": bool(route_match and '"UpdateConfig"' in route_match.group(1)),
        "update_config_request": bool(request_match),
        "approval_reference_carrier": bool(re.search(r"map<string,\s*string>\s+annotations\s*=", request)),
        "optimistic_concurrency": bool(re.search(r"uint64\s+expected_resource_version\s*=", request)),
        "incremental_merge": bool(re.search(r"repeated PolicyMergeOperation\s+merge_operations\s*=", request)),
        "validate_contract": "message ValidateEvaluation" in interceptor,
        "caller_identity_contract": "map<string, string> principal" in interceptor,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Optional local OpenShell checkout (no downloads)")
    parser.add_argument("--output", type=Path, default=Path(".approval-lab/openshell-probe.json"))
    args = parser.parse_args()
    report = {
        "source_commit": None if args.source_dir else SOURCE_COMMIT,
        "source_kind": "local_unverified_checkout" if args.source_dir else "pinned_upstream",
        "tools": {
            "openshell": check_command("openshell", ["--version"]),
            "docker": check_command("docker", ["info", "--format", "{{.ServerVersion}}"]),
            "wsl": check_command("wsl", ["--list", "--quiet"]),
        },
        "source_hashes": {}, "source_errors": {},
        "live_integration_verified": False,
    }
    sources = {}
    for path in SOURCE_PATHS:
        try:
            if args.source_dir:
                data = (args.source_dir / path).read_bytes()
            else:
                url = f"https://raw.githubusercontent.com/NVIDIA/OpenShell/{SOURCE_COMMIT}/{path}"
                with urllib.request.urlopen(url, timeout=20) as response:
                    data = response.read()
            sources[path] = data.decode("utf-8")
            report["source_hashes"][path] = hashlib.sha256(data).hexdigest()
        except (OSError, UnicodeError) as exc:
            report["source_errors"][path] = str(exc)
    report["contract_checks"] = inspect_sources(sources) if not report["source_errors"] else {}
    report["source_contract_verified"] = bool(report["contract_checks"]) and all(report["contract_checks"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["source_contract_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
