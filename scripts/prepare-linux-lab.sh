#!/usr/bin/env bash
# Run on a disposable Linux machine with Python 3.11+ and uv already installed.
# This script installs no OS packages and starts no OpenShell gateway.
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
  echo 'Run this script on a separate Linux test machine.' >&2
  exit 1
fi
command -v uv >/dev/null || { echo 'Existing uv installation required.' >&2; exit 1; }
python_executable="$(command -v "${LAB_PYTHON:-python3}")"
"$python_executable" -I -c 'import sys; assert sys.version_info >= (3, 11)'
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
run_root="$repo_root/.approval-lab/linux-run/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$run_root"/{temp,reports,data}
chmod 700 "$run_root" "$run_root/data"
export UV_CACHE_DIR="$repo_root/.approval-lab/linux-run/uv-cache"
export UV_PROJECT_ENVIRONMENT="$run_root/venv"
export UV_PYTHON_DOWNLOADS=never UV_NO_CONFIG=1 PYTHONNOUSERSITE=1
export TEMP="$run_root/temp" TMP="$run_root/temp" TMPDIR="$run_root/temp"
export PYTHONPYCACHEPREFIX="$run_root/temp/pycache"
export APPROVAL_LAB_DB="$run_root/data/approvals.sqlite3"
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
cd -- "$repo_root"
uv sync --locked --extra openshell --no-config --no-python-downloads \
  --python "$python_executable" --system-certs 2>&1 | tee "$run_root/reports/setup.log"
"$run_root/venv/bin/python" -m approval_lab.demo 2>&1 | tee "$run_root/reports/demo.log"
"$run_root/venv/bin/python" -m pytest -q --tb=short \
  --basetemp "$run_root/temp/pytest" -o "cache_dir=$run_root/temp/pytest-cache" \
  --junitxml "$run_root/reports/tests.xml" 2>&1 | tee "$run_root/reports/tests.log"
printf '\nProtocol tests finished. Python: %s\nReports: %s\n' "$run_root/venv/bin/python" "$run_root/reports"
printf 'No live OpenShell gateway was started; follow docs/openshell-bridge.zh-TW.md for live setup.\n'
